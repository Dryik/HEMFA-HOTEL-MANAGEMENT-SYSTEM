from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelFrontdeskSession(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Session Test Hotel", "code": "STH"}
        )
        cls.lyd_currency = cls.env.company.currency_id
        cls.usd_currency = cls.env["res.currency"].search([("name", "=", "USD")], limit=1)
        if not cls.usd_currency:
            cls.usd_currency = cls.env["res.currency"].create(
                {"name": "USD", "symbol": "$", "rounding": 0.01}
            )

        # Ensure active currency rates
        existing_rate = cls.env["res.currency.rate"].search(
            [
                ("currency_id", "=", cls.usd_currency.id),
                ("company_id", "=", cls.env.company.id),
                ("name", "=", fields.Date.today()),
            ]
        )
        if existing_rate:
            existing_rate.write({"rate": 0.2})
        else:
            cls.env["res.currency.rate"].create(
                {
                    "currency_id": cls.usd_currency.id,
                    "rate": 0.2, # 1 LYD = 0.2 USD (i.e. 1 USD = 5 LYD)
                    "company_id": cls.env.company.id,
                    "name": fields.Date.today(),
                }
            )

        cls.partner = cls.env["res.partner"].create({"name": "Session Guest"})

        cls.cash_journal = cls.env["account.journal"].search([("type", "=", "cash")], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env["account.journal"].create(
                {
                    "name": "Cash Drawer",
                    "type": "cash",
                    "code": "CASH1",
                }
            )

        # Ensure cashier has billing group access if it exists, to avoid AccessError in test runs
        invoice_group = cls.env.ref("account.group_account_invoice", raise_if_not_found=False)
        groups = [cls.env.ref("hotel_base.group_hotel_frontdesk").id]
        if invoice_group:
            groups.append(invoice_group.id)

        cls.cashier = cls.env["res.users"].create(
            {
                "name": "Test Cashier",
                "login": "tcashier",
                "groups_id": [(6, 0, groups)],
            }
        )

    def test_session_lifecycle(self):
        # 1. Open session
        session = self.env["hotel.frontdesk.session"].with_user(self.cashier).create(
            {
                "property_id": self.property.id,
                "opening_balance_ids": [
                    (0, 0, {"currency_id": self.lyd_currency.id, "amount": 200.0, "type": "opening"}),
                    (0, 0, {"currency_id": self.usd_currency.id, "amount": 50.0, "type": "opening"}), # 50 USD = 250 LYD
                ]
            }
        )
        self.assertEqual(session.state, "opened")
        # 200 + (50 / 0.2) = 200 + 250 = 450.0 LYD
        self.assertEqual(session.total_opening_balance, 450.0)

        # 2. Register a payment transaction during the session
        # Mock payment creation by the cashier
        payment = self.env["account.payment"].with_user(self.cashier).create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner.id,
                "amount": 100.0,
                "currency_id": self.lyd_currency.id,
                "journal_id": self.cash_journal.id,
            }
        )
        # Re-compute balances
        session._compute_balances()
        self.assertEqual(session.total_transactions, 100.0)

        # 3. Closing cash count & close session
        # Let's say cashier counts 550.0 LYD at the end of the day (450 opening + 100 transactions)
        with self.assertRaises(UserError):
            # Cannot close without defining closing cash control
            session.action_close_session()

        session.write({
            "closing_balance_ids": [
                (0, 0, {"currency_id": self.lyd_currency.id, "amount": 550.0, "type": "closing"}),
            ]
        })
        
        session.action_close_session()
        self.assertEqual(session.state, "closed")
        self.assertTrue(session.date_closed)
        self.assertEqual(session.difference, 0.0)
