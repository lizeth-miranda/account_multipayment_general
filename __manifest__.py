# Copyright 2026 Munin
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    'name': 'Account Multipayment General',
    'description': """
        Modulo Para Generar Pagos Multiples""",
    'version': '16.0.1.0.0',
    'license': 'AGPL-3',
    'author': 'Munin',
    'depends': [
        'account', 'account_payment', 'l10n_mx_edi',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizards/multi_payments.xml',
        'views/multi_payment_views.xml',
    ],
    'demo': [
    ],
}
