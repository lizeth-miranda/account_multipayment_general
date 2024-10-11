# Copyright 2026 Munin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class MultiPaymentsGeneral(models.TransientModel):
    _name = "multi.payments.general"
    _description = "Multi Pagos Generales"

    payment_date = fields.Date(String="Payment Date", required=True, default=fields.Date.context_today)
    memo = fields.Char(string="Memo")
    register_payment_line = fields.One2many("account.payment.register", 'multi_payment_general_id',
                                            string="Lineas de Facturas")
    available_partner_bank_ids = fields.Many2many(comodel_name='res.partner.bank', )

    journal_id = fields.Many2one('account.journal', string="Diario",
                                 default=lambda self: self.env['account.journal'].search([('type', '=', 'bank')],
                                                                                         limit=1))

    currency_id = fields.Many2one('res.currency', string="Moneda", compute='_compute_currency_id', store=True,
                                  readonly=False)
    amount_total = fields.Monetary(string="Monto Total", compute='_compute_amount_total', store=False)
    amount_residual = fields.Monetary(string="Monto Restante", compute="_compute_totals")
    payment_difference = fields.Monetary(compute='_compute_payment_difference')
    # == Payment difference fields ==
    payment_difference_handling = fields.Selection([('open', 'Keep open'), ('reconcile', 'Mark as fully paid'), ],
                                                   default='open', string="Payment Difference Handling")
    writeoff_account_id = fields.Many2one('account.account', string="Difference Account", copy=False,
                                          domain="[('deprecated', '=', False), ('company_id', '=', company_id)]")
    writeoff_label = fields.Char(string='Journal Item Label', default='Write-Off',
                                 help='Change label of the counterpart that will hold the payment difference')

    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    l10n_mx_edi_payment_method_id = fields.Many2one('l10n_mx_edi.payment.method', string="Metodo de Pago", )

    group_payment = fields.Boolean(string="Agrupar Pagos por Cliente", compute="_compute_group_payment", store=True,
                                   readonly=False, help="Agrupar pagos por cliente, se un pago para cada cliente")

    def _get_usage_selection(self):
        return self.env['account.move'].fields_get().get('l10n_mx_edi_usage').get('selection')

    l10n_mx_edi_usage = fields.Selection(_get_usage_selection, 'Usage', default='P01',
                                         help='This usage will be used instead of the default one for invoices.')

    @api.depends('register_payment_line.partner_id')
    def _compute_group_payment(self):
        for record in self:
            record.group_payment = len(record.register_payment_line.partner_id) > 1

    @api.depends('register_payment_line', 'register_payment_line.total_a_pagar', 'register_payment_line.amount',
                 'register_payment_line.payment_difference_handling')
    def _compute_amount_total(self):
        for record in self:
            record.amount_total = sum(record.register_payment_line.mapped(
                lambda x: x.amount if x.payment_difference_handling != 'reconcile' else x.total_a_pagar))

    @api.depends('register_payment_line', 'register_payment_line.amount', 'amount_total',
                 'register_payment_line.total_a_pagar')
    def _compute_payment_difference(self):
        for record in self:
            record.payment_difference = abs(
                sum(record.register_payment_line.mapped('total_a_pagar')) - record.amount_total)

    @api.depends('register_payment_line', 'register_payment_line.amount', 'amount_total')
    def _compute_totals(self):
        for record in self:
            record.amount_residual = record.amount_total - sum(record.register_payment_line.mapped('amount'))

    @api.depends('journal_id')
    def _compute_currency_id(self):
        for record in self:
            currency = record.journal_id and record.journal_id.currency_id or self.env.ref('base.MXN')
            record.currency_id = currency.id


    @api.onchange('journal_id')
    def onchange_journal_id(self):
        for reg_pay_id in self.register_payment_line:
            reg_pay_id.journal_id = self.journal_id.id

    @api.model
    def _compute_outstanding_account_id(self, pay, journal, payment_type, payment_method_line_id):
        if pay.payment_type == 'inbound':
            return (pay.payment_method_line_id.payment_account_id or
                    pay.journal_id.company_id.account_journal_payment_debit_account_id or
                    self.journal_id.company_id.account_journal_payment_debit_account_id)
        elif pay.payment_type == 'outbound':
            return (
                    pay.payment_method_line_id.payment_account_id or
                    pay.journal_id.company_id.account_journal_payment_credit_account_id or
                    self.journal_id.company_id.account_journal_payment_credit_account_id)
        else:
            return self.env['account.account']

    def create_payment_multi(self):
        move = self.create_multi_payment()
        return move

    @api.onchange('payment_date')
    def onchange_payment_date(self):
        for reg_pay_id in self.register_payment_line:
            reg_pay_id.payment_date = self.payment_date

    def create_multi_payment(self):
        self.check_payment_validity()
        other_data = self._pre_create_action()
        created_payments = self._create_payment_data(**other_data)
        created_payments = self._post_create_action(created_payments)
        action = {'name': _('Pagos'), 'type': 'ir.actions.act_window', 'res_model': 'account.payment',
                  'context': {'create': False}, }
        if len(created_payments) == 1:
            action.update({'view_mode': 'form', 'res_id': created_payments.id, })
        else:
            action.update({'view_mode': 'tree,form', 'domain': [('id', 'in', created_payments.ids)], })
        return action

    def _create_payment_data(self, **kwargs):
        payment_ids = self.env['account.payment']
        if self.group_payment:
            payment_data = {}
            for line in self.register_payment_line:
                payment_data.setdefault(line.partner_id,
                                        {'payment_amount': 0.0, 'wizard_lines': self.env['account.payment.register']})
                payment_data[line.partner_id]['wizard_lines'] += line
                payment_data[line.partner_id]['payment_amount'] += line.amount

            for partner, values in payment_data.items():
                amount_payment = values['payment_amount']
                wizard_lines = values['wizard_lines']
                account_payment = self.create_payment(partner=partner, amount_payment=amount_payment,
                                                      wizard_lines=wizard_lines, **kwargs)
                payment_ids += account_payment
        else:
            partners = [(partner, sum(self.register_payment_line.filtered(lambda p: p.partner_id == partner).mapped(
                lambda x: x.amount if x.payment_difference_handling != 'reconcile' else x.total_a_pagar))) for partner in
                        self.register_payment_line.partner_id]
            partner_id, amount = max(partners, key=lambda x: x[1])
            account_payment = self.create_payment(partner=partner_id, amount_payment=self.amount_total,
                                                  wizard_lines=self.register_payment_line, **kwargs)

            payment_ids += account_payment
        return payment_ids

    def create_payment(self, partner, amount_payment, wizard_lines, **kwargs):
        extra_move_vals = self._extra_payment_move_vals(partner, amount_payment, **kwargs)
        move_vals = {'l10n_mx_edi_usage': self.l10n_mx_edi_usage,
                     'partner_id': partner.id,
                     'invoice_user_id': self.env.uid,
                     'state': 'draft',
                     'amount': amount_payment,
                     'date': self.payment_date,
                     'ref': self.memo,
                     'currency_id': self.currency_id.id,
                     'journal_id': self.journal_id.id,
                     'l10n_mx_edi_payment_method_id': self.l10n_mx_edi_payment_method_id.id,
                     'move_type': 'entry',
                     'line_ids': [(0, 0, line_vals) for line_vals in
                                  wizard_lines._prepare_payment_move_line_default_vals()], }
        move_vals.update(extra_move_vals)
        move = self.env['account.payment'].create(move_vals)
        move.action_post()
        # Reconcile the account.move.line of the payment with the account.move.line of the invoice.
        payment_lines = move.line_ids
        lines = wizard_lines
        for account in payment_lines.account_id:
            for line in lines:
                invoice_lines = line.line_ids
                payment_line = payment_lines.filtered(lambda x: x.temp_id == line.id)
                (payment_line + invoice_lines).filtered_domain(
                    [('account_id', '=', account.id), ('reconciled', '=', False)]).with_context(
                    no_exchange_difference=True).reconcile()
        move.move_id._update_payments_edi_documents()
        move.move_id.edi_document_ids.filtered(
            lambda x: x.edi_format_id != self.env.ref('l10n_mx_edi.edi_cfdi_3_3')).write({'state': False})
        return move

    def _extra_payment_move_vals(self, partner, amount_payment, **kwargs):
        return {}

    def check_payment_validity(self):
        return True

    def _post_create_action(self, created_payments):
        return created_payments

    def _pre_create_action(self):
        return {}