from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelFolio(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor F1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Folio Suite",
                "base_price": 400.0,
                "property_id": cls.property.id,
            }
        )
        cls.room_type.product_id.taxes_id = [(5, 0, 0)]
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "R201",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "Guest Mitchell", "is_hotel_guest": True}
        )
        cls.agency = cls.env["res.partner"].create(
            {"name": "Agency Libya Travel", "is_hotel_agency": True}
        )
        cls.frontdesk_user = cls.env["res.users"].create(
            {
                "name": "Folio Front Desk",
                "login": "folio_frontdesk_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)
                ],
            }
        )
        cls.manager_user = cls.env["res.users"].create(
            {
                "name": "Folio Manager",
                "login": "folio_manager_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_manager").id)
                ],
            }
        )

        # Create product categories
        cls.room_service_categ = cls.env["product.category"].create(
            {"name": "Room Service"}
        )
        cls.other_categ = cls.env["product.category"].create(
            {"name": "Other Services"}
        )

        # Create products
        cls.burger = cls.env["product.product"].create(
            {
                "name": "Burger",
                "type": "consu",
                "list_price": 15.0,
                "categ_id": cls.room_service_categ.id,
                "taxes_id": [(6, 0, [])],
            }
        )
        cls.laundry = cls.env["product.product"].create(
            {
                "name": "Laundry Service",
                "type": "service",
                "list_price": 10.0,
                "categ_id": cls.other_categ.id,
                "taxes_id": [(6, 0, [])],
            }
        )

        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def _reservation(self, use_agency=False, offset_days=0):
        checkin = self.checkin + timedelta(days=offset_days)
        return self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "agency_id": self.agency.id if use_agency else False,
                "property_id": self.property.id,
                "room_id": self.room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=2),
                "state": "draft",
            }
        )

    def _group_reservation(self, offset_days=0):
        second_room = self.env["hotel.room"].search(
            [("property_id", "=", self.property.id), ("name", "=", "R202")],
            limit=1,
        ) or self.env["hotel.room"].create(
            {
                "name": "R202",
                "floor_id": self.floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        checkin = self.checkin + timedelta(days=offset_days)
        group = self.env["hotel.reservation.group"].create(
            {
                "property_id": self.property.id,
                "group_partner_id": self.guest.id,
                "billing_partner_id": self.guest.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=2),
                "allocation_line_ids": [
                    Command.create(
                        {"room_type_id": self.room_type.id, "requested_qty": 2}
                    )
                ],
            }
        )
        group.action_allocate_available()
        group.action_confirm()
        self.assertEqual(
            set(group.member_ids.mapped("room_id").ids),
            {self.room.id, second_room.id},
        )
        return group

    def test_folio_auto_creation(self):
        res = self._reservation()
        self.assertEqual(res.folio_count, 0)
        res.action_confirm()
        self.assertEqual(res.folio_count, 1)
        
        folio = res.folio_ids[0]
        self.assertTrue(folio.name.startswith("FOLIO/"))
        self.assertEqual(folio.partner_id, self.guest)
        stay_line = folio.line_ids.filtered(
            lambda line: line.source_type == "room_night"
        )
        self.assertEqual(sum(stay_line.mapped("qty")), 2.0)
        self.assertEqual(sum(stay_line.mapped("amount_total")), 800.0)

    def test_cancellation_reverses_contracted_stay(self):
        reservation = self._reservation()
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        stay_line = folio.line_ids.filtered(
            lambda line: line.source_type == "room_night"
        )

        reservation.action_cancel()

        reversal = folio.line_ids.filtered(
            lambda line: line.source_type == "reversal"
        )
        self.assertEqual(len(reversal), len(stay_line))
        self.assertEqual(sum(reversal.mapped("qty")), -sum(stay_line.mapped("qty")))
        self.assertEqual(reversal.mapped("payee_partner_id"), self.guest)
        self.assertEqual(reversal.mapped("reversal_of_id"), stay_line)
        self.assertEqual(folio.amount_total, 0.0)

        reservation.action_reset_draft()
        reservation.action_confirm()
        self.assertEqual(folio.amount_total, 800.0)
        reservation._ensure_stay_charge()
        self.assertEqual(folio.amount_total, 800.0)

    def test_per_night_policy_posts_only_due_snapshot_and_is_idempotent(self):
        self.property.stay_charge_policy = "per_night"
        business_date = self.property.get_business_date()
        checkin, _unused = self.property.get_business_day_bounds(business_date)
        reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "property_id": self.property.id,
                "room_id": self.room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=2),
            }
        )
        reservation.action_confirm()

        self.assertEqual(len(reservation.rate_line_ids), 2)
        self.assertEqual(len(reservation.rate_line_ids.filtered("posted")), 1)
        stay_lines = reservation.folio_ids.line_ids.filtered(
            lambda line: line.source_type == "room_night"
        )
        self.assertEqual(len(stay_lines), 1)

        self.env["hotel.reservation"]._cron_post_due_nightly_rates()
        self.assertEqual(
            len(
                reservation.folio_ids.line_ids.filtered(
                    lambda line: line.source_type == "room_night"
                )
            ),
            1,
        )

    def test_group_combined_and_isolated_invoice_workflows(self):
        combined_group = self._group_reservation()
        combined_action = combined_group.action_create_group_invoice()
        combined_invoice = self.env["account.move"].browse(combined_action["res_id"])
        self.assertEqual(combined_invoice.hotel_reservation_group_id, combined_group)
        self.assertEqual(len(combined_invoice.invoice_line_ids), 4)
        self.assertEqual(
            combined_group.member_ids.mapped("folio_ids.invoice_ids"),
            combined_invoice,
        )

        isolated_group = self._group_reservation(offset_days=10)
        isolated_action = isolated_group.action_create_isolated_invoices()
        isolated_invoices = self.env["account.move"].search(isolated_action["domain"])
        self.assertEqual(len(isolated_invoices), 2)
        self.assertEqual(
            set(isolated_invoices.mapped("hotel_folio_id").ids),
            set(isolated_group.member_ids.mapped("folio_ids").ids),
        )

    def test_new_folio_totals_are_safe_before_reservation_selection(self):
        folio = self.env["hotel.folio"].new({})

        self.assertFalse(folio.currency_id)
        self.assertEqual(folio.amount_due, 0.0)
        self.assertEqual(folio.amount_paid, 0.0)
        self.assertTrue(folio.is_open)

    def test_add_charges(self):
        res = self._reservation()
        res.action_confirm()
        folio = res.folio_ids[0]
        
        line1 = folio.add_charge(self.burger, qty=2.0)
        self.assertEqual(line1.amount, 30.0)
        self.assertEqual(line1.payee_partner_id, self.guest)
        self.assertEqual(folio.amount_total, 830.0)
        with self.assertRaises(UserError):
            line1.write({"source_type": "pos", "source_key": "pos:forged"})
        with self.assertRaises(UserError):
            folio.add_charge(
                self.burger,
                source_type="pos",
                source_key="pos:forged",
            )

    def test_tax_discount_and_invoice_totals_match(self):
        tax = self.env["account.tax"].create(
            {
                "name": "Hotel Test VAT 10%",
                "amount": 10.0,
                "type_tax_use": "sale",
                "company_id": self.property.company_id.id,
            }
        )
        reservation = self._reservation()
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        line = folio.add_charge(
            self.burger,
            qty=2.0,
            discount=10.0,
            tax_ids=tax.ids,
        )
        self.assertAlmostEqual(line.amount_untaxed, 27.0)
        self.assertAlmostEqual(line.amount_tax, 2.7)
        self.assertAlmostEqual(line.amount_total, 29.7)
        self.assertAlmostEqual(line.amount, line.amount_total)

        action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        self.assertAlmostEqual(invoice.amount_untaxed, folio.amount_untaxed)
        self.assertAlmostEqual(invoice.amount_tax, folio.amount_tax)
        self.assertAlmostEqual(invoice.amount_total, folio.amount_total)

    def test_manual_fx_requires_reason_and_records_approver(self):
        foreign = self.env["res.currency"].with_context(active_test=False).search(
            [("id", "!=", self.env.company.currency_id.id)], limit=1
        )
        self.assertTrue(foreign)
        foreign.active = True
        reservation = self._reservation()
        reservation.currency_id = foreign
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        folio.add_charge(self.burger, qty=1.0)
        action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        old_rate = invoice.invoice_currency_rate

        with self.assertRaises(UserError):
            invoice.with_user(self.manager_user).write(
                {"invoice_currency_rate": old_rate * 1.05}
            )

        with self.assertRaises(UserError):
            self.env["hotel.manual.fx.wizard"].with_user(
                self.manager_user
            ).create(
                {
                    "move_id": invoice.id,
                    "new_rate": old_rate * 1.1,
                    "reason": " ",
                }
            ).action_apply()

        wizard = self.env["hotel.manual.fx.wizard"].with_user(
            self.manager_user
        ).create(
            {
                "move_id": invoice.id,
                "new_rate": old_rate * 1.1,
                "reason": "Approved front-desk contract rate",
            }
        )
        wizard.action_apply()
        self.assertAlmostEqual(invoice.invoice_currency_rate, old_rate * 1.1)
        self.assertTrue(
            invoice.company_currency_id.is_zero(
                sum(invoice.line_ids.mapped("balance"))
            )
        )
        self.assertEqual(invoice.hotel_manual_fx_user_id, self.manager_user)
        self.assertEqual(
            invoice.hotel_manual_fx_reason,
            "Approved front-desk contract rate",
        )

    def test_routing_rules(self):
        # Create a routing rule: route room service to the agency
        self.env["hotel.folio.routing.rule"].create(
            {
                "name": "Route Room Service to Agency",
                "property_id": self.property.id,
                "category_id": self.room_service_categ.id,
                "routing_type": "agency",
                "active": True,
            }
        )

        res = self._reservation(use_agency=True)
        res.action_confirm()
        folio = res.folio_ids[0]

        # Add room service charge (burger) -> should go to agency
        line_routed = folio.add_charge(self.burger, qty=1.0)
        self.assertEqual(line_routed.payee_partner_id, self.agency)

        # Add other category charge (laundry) -> should stay on guest
        line_guest = folio.add_charge(self.laundry, qty=1.0)
        self.assertEqual(line_guest.payee_partner_id, self.guest)

    def test_due_uses_linked_native_receivable_residuals(self):
        reservation = self._reservation()
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        folio.add_charge(self.burger, qty=2.0)

        payment = self.env["account.payment"].create(
            {
                "amount": 10.0,
                "date": fields.Date.today(),
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.guest.id,
                "currency_id": folio.currency_id.id,
                "hotel_property_id": self.property.id,
                "hotel_folio_id": folio.id,
                "hotel_payment_purpose": "guest_deposit",
            }
        )
        payment.action_post()
        with self.assertRaises(UserError):
            payment.write({"hotel_folio_id": False})
        folio._compute_totals()
        self.assertAlmostEqual(folio.amount_total, 830.0)
        self.assertAlmostEqual(folio.amount_paid, 10.0)
        self.assertAlmostEqual(folio.amount_due, 820.0)

        action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        invoice.action_post()
        receivable_lines = (invoice | payment.move_id).line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        receivable_lines.reconcile()
        folio._compute_totals()
        self.assertAlmostEqual(folio.amount_invoiced, 830.0)
        self.assertAlmostEqual(folio.amount_paid, 10.0)
        self.assertAlmostEqual(folio.amount_due, 820.0)

    def test_frontdesk_registers_guest_deposit_from_folio(self):
        reservation = self._reservation()
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        journal = self.env["account.journal"].search(
            [
                ("company_id", "=", self.property.company_id.id),
                ("type", "in", ("bank", "cash")),
            ],
            limit=1,
        )
        self.assertTrue(journal)
        self.property.deposit_journal_id = journal

        action = folio.with_user(
            self.frontdesk_user
        ).action_open_register_deposit()
        wizard_model = (
            self.env["hotel.register.payment.wizard"]
            .with_user(self.frontdesk_user)
            .with_context(action["context"])
        )
        defaults = wizard_model.default_get(
            [
                "folio_id",
                "payment_purpose",
                "partner_id",
                "journal_id",
                "payment_date",
            ]
        )
        self.assertEqual(defaults["folio_id"], folio.id)
        self.assertEqual(defaults["payment_purpose"], "guest_deposit")
        self.assertEqual(defaults["partner_id"], self.guest.id)
        self.assertEqual(defaults["journal_id"], journal.id)
        wizard = wizard_model.create(
            {
                **defaults,
                "amount": 125.0,
                "payment_reference": "Front desk receipt 42",
            }
        )
        wizard.action_register()

        payment = folio.sudo().payment_ids.filtered(
            lambda record: record.hotel_payment_purpose == "guest_deposit"
            and record.amount == 125.0
        )
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.partner_id, self.guest)
        self.assertEqual(payment.journal_id, journal)
        self.assertIn(payment.state, ("in_process", "paid"))
        self.assertTrue(
            folio.message_ids.filtered(
                lambda message: "Front Desk" in (message.body or "")
            )
        )

    def test_frontdesk_registers_agency_advance_from_folio(self):
        reservation = self._reservation(use_agency=True)
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        journal = self.env["account.journal"].search(
            [
                ("company_id", "=", self.property.company_id.id),
                ("type", "in", ("bank", "cash")),
            ],
            limit=1,
        )
        self.assertTrue(journal)
        self.property.advance_journal_id = journal

        action = folio.with_user(
            self.frontdesk_user
        ).action_open_register_advance()
        wizard = (
            self.env["hotel.register.payment.wizard"]
            .with_user(self.frontdesk_user)
            .with_context(action["context"])
            .create({"amount": 300.0})
        )
        wizard.action_register()

        payment = folio.sudo().payment_ids.filtered(
            lambda record: record.hotel_payment_purpose == "agency_advance"
            and record.amount == 300.0
        )
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.partner_id, self.agency)
        self.assertEqual(payment.journal_id, journal)
        self.assertIn(payment.state, ("in_process", "paid"))

    def test_invoicing(self):
        res = self._reservation()
        res.action_confirm()
        folio = res.folio_ids[0]

        folio.add_charge(self.burger, qty=1.0)
        folio.add_charge(self.laundry, qty=2.0)
        self.assertEqual(folio.amount_total, 835.0)

        with self.assertRaises(UserError):
            folio.with_user(self.frontdesk_user).action_create_invoice()

        # Create Guest Invoice
        action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(invoice.partner_id, self.guest)
        self.assertEqual(len(invoice.invoice_line_ids), 4)
        self.assertEqual(invoice.amount_untaxed, 835.0)

        # All lines should now be marked as posted
        self.assertTrue(all(line.is_posted for line in folio.line_ids))

        # Test deletion protection
        with self.assertRaises(UserError):
            folio.unlink()
        with self.assertRaises(UserError):
            folio.write({"name": "FORGED-FOLIO"})
        with self.assertRaises(UserError):
            folio.write({"invoice_ids": [(5, 0, 0)]})
        with self.assertRaises(UserError):
            folio.line_ids[0].unlink()

        # Trying to invoice again should raise error since there are no uninvoiced lines
        with self.assertRaises(UserError):
            folio.action_create_invoice()

        posted_line = folio.line_ids[0]
        with self.assertRaises(UserError):
            posted_line.write({"qty": 99.0})
        with self.assertRaises(UserError):
            posted_line.write({"is_posted": False, "lock_state": "unlocked"})
        with self.assertRaises(UserError):
            posted_line.with_user(self.manager_user).with_context(
                hotel_financial_reversal=True, hotel_migration=True
            ).write({"qty": 98.0})
        with self.assertRaises(UserError):
            posted_line.with_user(self.frontdesk_user).action_reverse("Not authorized")

        reversal = posted_line.with_user(self.manager_user).action_reverse(
            "Incorrect charge"
        )
        self.assertEqual(reversal.reversal_of_id, posted_line)
        self.assertEqual(reversal.amount, -posted_line.amount)
        self.assertTrue(reversal.is_posted)
        self.assertEqual(reversal.reversed_by_id, self.manager_user)
        with self.assertRaises(UserError):
            posted_line.with_user(self.manager_user).action_reverse("Duplicate")

        # Workflow charges stay immutable before invoicing; manual lines and
        # empty draft folios remain deletable.
        res2 = self._reservation(offset_days=5)
        res2.action_confirm()
        folio2 = res2.folio_ids[0]
        manual_line = folio2.add_charge(self.burger, qty=1.0)
        self.assertFalse(any(line.is_posted for line in folio2.line_ids))
        workflow_line = folio2.line_ids.filtered(
            lambda line: line.source_type == "room_night"
        )
        with self.assertRaises(UserError):
            workflow_line.unlink()
        with self.assertRaises(UserError):
            folio2.unlink()
        manual_line.unlink()

        draft_reservation = self._reservation(offset_days=8)
        empty_folio = self.env["hotel.folio"].create(
            {"reservation_id": draft_reservation.id}
        )
        empty_folio.unlink()

    def test_folio_is_open(self):
        res = self._reservation()
        res.action_confirm()
        folio = res.folio_ids[0]
        # The full contracted stay is charged on confirmation.
        self.assertTrue(folio.is_open)
        self.assertEqual(folio.property_id, self.property)

        res.action_check_in()
        folio.add_charge(self.burger, qty=1.0)
        self.assertTrue(folio.is_open)
        self.assertEqual(folio.amount_due, 815.0)

        res.checkout_balance_override_reason = "Approved test checkout balance"
        res.action_check_out()
        # Checked out with balance still due remains open.
        self.assertTrue(folio.is_open)

        action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        invoice.action_post()
        payment = self.env["account.payment"].create(
            {
                "amount": 815.0,
                "date": fields.Date.today(),
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.guest.id,
                "currency_id": folio.currency_id.id,
                "hotel_property_id": self.property.id,
                "hotel_folio_id": folio.id,
                "hotel_payment_purpose": "folio_settlement",
            }
        )
        payment.action_post()
        receivable_lines = (invoice | payment.move_id).line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        receivable_lines.reconcile()
        folio._compute_totals()
        self.assertEqual(folio.amount_due, 0.0)
        self.assertFalse(folio.is_open)

    def test_folio_today_filter_uses_odoo_datetime(self):
        arch = self.env.ref("hotel_folio.hotel_folio_view_search").arch_db
        self.assertIn("datetime.timedelta(days=1)", arch)
        self.assertNotIn("+ timedelta(days=1)", arch)
