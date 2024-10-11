# Copyright 2026 Munin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    is_multipayment_record = fields.Boolean(string="Is Multipayment?",
                                            compute="_compute_is_multipayment")


    def action_open_multipayment_wizard(self):
        rec_vals = []
        for invoice_id in self:
            res = {}
            lines = invoice_id.line_ids
            available_lines = self.env['account.move.line']
            for line in lines:
                if line.move_id.state != 'posted':
                    raise UserError(_("You can only register payment for posted journal entries."))

                if line.account_type not in ('asset_receivable', 'liability_payable'):
                    continue
                if line.currency_id:
                    if line.currency_id.is_zero(line.amount_residual_currency):
                        continue
                else:
                    if line.company_currency_id.is_zero(line.amount_residual):
                        continue
                available_lines |= line

            # Check.
            if not available_lines:
                raise UserError(_(
                    "You can't register a payment because there is nothing left to pay on the selected journal items."))
            if len(lines.company_id) > 1:
                raise UserError(_("You can't create payments for entries belonging to different companies."))
            if len(set(available_lines.mapped('account_type'))) > 1:
                raise UserError(
                    _("You can't register payments for journal items being either all inbound, either all outbound."))

            res['line_ids'] = [(6, 0, available_lines.ids)]
            values = {
                'partner_id': available_lines[0].partner_id.id,
                'line_ids': res['line_ids'],
            }
            register_payment_id = self.env['account.payment.register'].create(values)
            register_payment_id._compute_communication()
            rec_vals.append(register_payment_id)

        journal_id = self.env['account.journal'].search([('type', '=', 'bank'),
                                                         ('company_id', '=', self.env.user.company_id.id)],
                                                        limit=1)
        for rec in rec_vals:
            rec.journal_id = journal_id.id
        res = self.env['multi.payments.general'].create({'journal_id': journal_id.id,
                                                             'l10n_mx_edi_payment_method_id':
                                                                 fields.first(self).l10n_mx_edi_payment_method_id.id,
                                                             'l10n_mx_edi_usage': fields.first(self).l10n_mx_edi_usage,
                                                             })
        res.register_payment_line = [record.id for record in rec_vals]
        return {
            'name': _('Register Payment Multi Invoice'),
            'res_model': 'multi.payments.general',
            'view_mode': 'form',
            'target': 'new',
            'res_id': res.id,
            'type': 'ir.actions.act_window', }

    @api.depends('line_ids.temp_id')
    def _compute_is_multipayment(self):
        for record in self:
            record.is_multipayment_record = len([line for line in record.line_ids if line.temp_id]) > 0

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    temp_id = fields.Integer(string='Temp ID', copy=False)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _synchronize_from_moves(self, changed_fields):
        if self._context.get('skip_account_move_synchronization'):
            return
        to_change = self.filtered(lambda l: not l.move_id.is_multipayment_record)
        if to_change:
            res = super(AccountPayment, to_change)._synchronize_from_moves(changed_fields)
        else:
            res = True
        return res

    def _synchronize_to_moves(self, changed_fields):
        if self._context.get('skip_account_move_synchronization'):
            return
        to_change = self.filtered(lambda l: not l.move_id.is_multipayment_record)
        if to_change:
            res = super(AccountPayment, to_change)._synchronize_to_moves(changed_fields)
        else:
            res = True
        return res
