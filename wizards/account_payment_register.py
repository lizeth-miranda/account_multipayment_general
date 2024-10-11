# Copyright 2022 Munin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models, api


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    multi_payment_general_id = fields.Many2one("multi.payments.general")
    total_a_pagar = fields.Monetary(string='Total a Pagar', readonly=True, store=True, compute="_total_payment")

    @api.depends('can_edit_wizard', 'source_amount', 'source_amount_currency', 'source_currency_id', 'company_id',
                 'currency_id', 'payment_date')
    def _compute_amount(self):
        for wizard in self:
            if wizard.multi_payment_general_id:
                continue
            if wizard.source_currency_id and wizard.can_edit_wizard:
                batch_result = wizard._get_batches()[0]
                wizard.amount = wizard._get_total_amount_in_wizard_currency_to_full_reconcile(batch_result)[0]
            else:
                # The wizard is not editable so no partial payment allowed and then, 'amount' is not used.
                wizard.amount = None

    @api.depends('source_amount', 'source_amount_currency', 'source_currency_id', 'company_id', 'currency_id',
                 'payment_date', 'multi_payment_general_id.currency_id')
    def _total_payment(self):
        for wizard in self:
            if not wizard.multi_payment_general_id:
                wizard.total_a_pagar = 0
                continue

            batch_result = wizard._get_batches()[0]
            total_amount_residual_in_wizard_currency = wizard\
                ._get_total_amount_in_wizard_currency_to_full_reconcile(batch_result, early_payment_discount=False)[0]

            wizard.total_a_pagar = total_amount_residual_in_wizard_currency

    def _prepare_payment_move_line_default_vals(self):
        ''' Prepare the dictionary to create the default account.move.lines for the current payment.
        :return: A list of python dictionary to be passed to the account.move.line's 'create' method.
        '''
        res = []

        for line in self:
            payment_vals = line._create_payment_vals_from_wizard(False)
            write_off_line_vals = payment_vals.get('write_off_line_vals', [])
            out_standing_line_vals = line.multi_payment_general_id._compute_outstanding_account_id(line,
                                                                                           line.journal_id,
                                                                                           line.payment_type,
                                                                                           line.payment_method_line_id)
            if not out_standing_line_vals:
                raise UserError(_(
                    "You can't create a new payment without an outstanding payments/receipts account set either on the company or the %s payment method in the %s journal.",
                    line.payment_method_line_id.name, line.journal_id.display_name))

            # Compute amounts.
            if write_off_line_vals:
                write_off_amount_currency = write_off_line_vals[0].get('amount_currency', 0.0)
            else:
                write_off_amount_currency = 0.0
            if line.payment_type == 'inbound':
                # Receive money.
                liquidity_amount_currency = line.amount
            elif line.payment_type == 'outbound':
                # Send money.
                liquidity_amount_currency = -line.amount
                write_off_amount_currency *= -1
            else:
                liquidity_amount_currency = write_off_amount_currency = 0.0

            write_off_balance = line.currency_id._convert(
                write_off_amount_currency,
                line.company_id.currency_id,
                line.company_id,
                line.payment_date,
            )
            liquidity_balance = line.currency_id._convert(
                liquidity_amount_currency,
                line.company_id.currency_id,
                line.company_id,
                line.payment_date,
            )
            counterpart_amount_currency = -liquidity_amount_currency - write_off_amount_currency
            counterpart_balance = -liquidity_balance - write_off_balance
            currency_id = line.currency_id.id

            if line.partner_id and line.partner_id == line.journal_id.company_id.partner_id:
                if line.payment_type == 'inbound':
                    liquidity_line_name = _('Transfer to %s', line.journal_id.name)
                else:  # payment.payment_type == 'outbound':
                    liquidity_line_name = _('Transfer from %s', line.journal_id.name)
            else:
                liquidity_line_name = False

            line_vals_list = [
                # Liquidity line.
                {
                    'name': liquidity_line_name,
                    'date_maturity': line.payment_date,
                    'amount_currency': liquidity_amount_currency,
                    'currency_id': currency_id,
                    'debit': liquidity_balance if liquidity_balance > 0.0 else 0.0,
                    'credit': -liquidity_balance if liquidity_balance < 0.0 else 0.0,
                    'partner_id': line.partner_id.id,
                    'account_id': out_standing_line_vals.id,
                },
                # Receivable / Payable.
                {
                    'name': line.communication,
                    'date_maturity': line.payment_date,
                    'amount_currency': counterpart_amount_currency,
                    'currency_id': currency_id,
                    'debit': counterpart_balance if counterpart_balance > 0.0 else 0.0,
                    'credit': -counterpart_balance if counterpart_balance < 0.0 else 0.0,
                    'partner_id': line.partner_id.id,
                    'account_id': payment_vals['destination_account_id'],
                },
            ]
            if not line.currency_id.is_zero(write_off_amount_currency):
                # Write-off line.
                line_vals_list.append({
                    'name': write_off_line_vals[0].get('name'),
                    'amount_currency': write_off_amount_currency,
                    'currency_id': currency_id,
                    'debit': write_off_balance if write_off_balance > 0.0 else 0.0,
                    'credit': -write_off_balance if write_off_balance < 0.0 else 0.0,
                    'partner_id': line.partner_id.id,
                    'account_id': write_off_line_vals[0].get('account_id'),
                })
            for x in line_vals_list:
                x['temp_id'] = line.id
            res.extend(line_vals_list)
        return res

    @api.depends('journal_id', 'multi_payment_general_id.currency_id')
    def _compute_currency_id(self):
        for wizard in self:
            wizard.currency_id = wizard.multi_payment_general_id.currency_id or\
                                 wizard.journal_id.currency_id or\
                                 wizard.source_currency_id or\
                                 wizard.company_id.currency_id
