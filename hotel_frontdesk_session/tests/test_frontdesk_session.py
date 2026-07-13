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
        
        # Determine standard currencies and mock rate relation
        cls.company_currency = cls.env.company.currency_id
        
        # Ensure we have a second currency that is different from company currency
        foreign_name = "EUR" if cls.company_currency.name == "USD" else "USD"
        cls.foreign_currency = cls.env["res.currency"].with_context(active_test=False).search(
            [("name", "=", foreign_name)], limit=1
        )
        if cls.foreign_currency:
            cls.foreign_currency.write({"active": True})
        else:
            symbol = "€" if foreign_name == "EUR" else "$"
            cls.foreign_currency = cls.env["res.currency"].create(
                {"name": foreign_name, "symbol": symbol, "rounding": 0.01, "active": True}
            )

        # Ensure active currency rates for foreign currency relative to company currency
        existing_rate = cls.env["res.currency.rate"].search(
            [
                ("currency_id", "=", cls.foreign_currency.id),
                ("company_id", "=", cls.env.company.id),
                ("name", "=", fields.Date.today()),
            ]
        )
        if existing_rate:
            existing_rate.write({"rate": 0.2})
        else:
            cls.env["res.currency.rate"].create(
                {
                    "currency_id": cls.foreign_currency.id,
                    "rate": 0.2, # 1 CompanyCurrency = 0.2 ForeignCurrency (i.e. 1 ForeignCurrency = 5 CompanyCurrency)
                    "company_id": cls.env.company.id,
                    "name": fields.Date.today(),
                }
            )

        cls.partner = cls.env["res.partner"].create(
            {"name": "Session Guest", "is_hotel_guest": True}
        )

        cls.cash_journal = cls.env["account.journal"].search([("type", "=", "cash")], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env["account.journal"].create(
                {
                    "name": "Cash Drawer",
                    "type": "cash",
                    "code": "CASH1",
                }
            )

        cls.cashier = cls.env["res.users"].create(
            {
                "name": "Test Cashier",
                "login": "tcashier",
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )

        # Assign groups via res.groups user_ids
        group_cashier = cls.env.ref("hotel_base.group_hotel_cashier")
        group_cashier.write({"user_ids": [(4, cls.cashier.id)]})

    def test_session_lifecycle(self):
        # 1. Open session
        session = self.env["hotel.frontdesk.session"].with_user(self.cashier).create(
            {
                "property_id": self.property.id,
                "opening_balance_ids": [
                    (0, 0, {"currency_id": self.company_currency.id, "journal_id": self.cash_journal.id, "amount": 200.0, "type": "opening"}),
                    (0, 0, {"currency_id": self.foreign_currency.id, "journal_id": self.cash_journal.id, "amount": 50.0, "type": "opening"}), # 50 Foreign = 250 Company
                ]
            }
        )
        self.assertEqual(session.state, "opened")
        # 200 + (50 / 0.2) = 200 + 250 = 450.0
        self.assertEqual(session.total_opening_balance, 450.0)

        # 2. Register a payment transaction during the session
        # Mock payment creation by the cashier
        wizard = self.env["hotel.cashier.payment.wizard"].with_user(
            self.cashier
        ).create(
            {
                "session_id": session.id,
                "property_id": self.property.id,
                "partner_id": self.partner.id,
                "amount": 100.0,
                "currency_id": self.company_currency.id,
                "journal_id": self.cash_journal.id,
                "payment_type": "inbound",
                "purpose": "guest_deposit",
            }
        )
        wizard.action_post_payment()
        payment = session.payment_ids
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.hotel_property_id, self.property)
        self.assertEqual(payment.hotel_frontdesk_session_id, session)
        self.assertIn(payment.state, ("in_process", "paid"))
        session._compute_balances()
        session.invalidate_recordset(["total_transactions"])
        self.assertEqual(session.total_transactions, 100.0)

        with self.assertRaises(UserError):
            session.write({"state": "closed"})
        with self.assertRaises(UserError):
            session.with_context(hotel_close_session=True).write({"state": "closed"})

        # 3. Closing cash count & close session
        # Let's say cashier counts 550.0 Company Currency units at the end of the day (450 opening + 100 transactions)
        with self.assertRaises(UserError):
            # Cannot close without defining closing cash control
            session.action_close_session()

        session.write({
            "closing_balance_ids": [
                (0, 0, {"currency_id": self.company_currency.id, "journal_id": self.cash_journal.id, "amount": 550.0, "type": "closing"}),
            ]
        })
        
        session.action_close_session()
        self.assertEqual(session.state, "closed")
        self.assertTrue(session.date_closed)
        self.assertEqual(session.difference, 0.0)

        # Deleting closed session is blocked
        with self.assertRaises(UserError):
            session.sudo().unlink()

        # Deleting opened session is allowed
        session2 = self.env["hotel.frontdesk.session"].sudo().create(
            {
                "property_id": self.property.id,
                "user_id": self.cashier.id,
            }
        )
        self.assertEqual(session2.state, "opened")
        session2.unlink()

    def test_today_filter_uses_odoo_datetime(self):
        arch = self.env.ref(
            "hotel_frontdesk_session.hotel_frontdesk_session_view_search"
        ).arch_db
        self.assertIn("datetime.timedelta(days=1)", arch)
        self.assertNotIn("+ timedelta(days=1)", arch)

    def test_cash_journal_domain_uses_simple_parent_company(self):
        domain = self.env["hotel.frontdesk.session.cash"]._fields["journal_id"].domain
        self.assertIn("parent.company_id", domain)
        self.assertNotIn("parent.property_id.company_id", domain)

    def test_session_action_uses_declared_search_view(self):
        action = self.env.ref(
            "hotel_frontdesk_session.hotel_frontdesk_session_action"
        )
        search_view = self.env.ref(
            "hotel_frontdesk_session.hotel_frontdesk_session_view_search"
        )
        self.assertEqual(action.search_view_id, search_view)

    def test_session_opening_metadata_cannot_be_forged(self):
        with self.assertRaises(UserError):
            self.env["hotel.frontdesk.session"].with_user(self.cashier).create(
                {
                    "property_id": self.property.id,
                    "name": "FORGED-SESSION",
                    "date_opened": fields.Datetime.now() - timedelta(days=7),
                }
            )
