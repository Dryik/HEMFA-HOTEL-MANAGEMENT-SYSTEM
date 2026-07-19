from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestRestrictedServices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor R1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Restricted Suite",
                "base_price": 300.0,
                "property_id": cls.property.id,
            }
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "R301",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "Guest Restricted", "is_hotel_guest": True}
        )
        cls.agency = cls.env["res.partner"].create(
            {"name": "Entity With Ceiling", "is_hotel_agency": True}
        )

        cls.minibar_categ = cls.env["product.category"].create(
            {"name": "Minibar"}
        )
        cls.restaurant_categ = cls.env["product.category"].create(
            {"name": "Restaurant"}
        )
        cls.soda = cls.env["product.product"].create(
            {
                "name": "Soda",
                "type": "consu",
                "list_price": 5.0,
                "categ_id": cls.minibar_categ.id,
                "taxes_id": [(6, 0, [])],
            }
        )
        cls.dinner = cls.env["product.product"].create(
            {
                "name": "Dinner",
                "type": "consu",
                "list_price": 40.0,
                "categ_id": cls.restaurant_categ.id,
                "taxes_id": [(6, 0, [])],
            }
        )

        cls.frontdesk_user = cls.env["res.users"].create(
            {
                "name": "Frontdesk Only",
                "login": "frontdesk_restricted_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)
                ],
            }
        )
        # Odoo 19 has_group checks real membership even for the test
        # superuser, so overrides need an actual supervisor user.
        cls.supervisor_user = cls.env["res.users"].create(
            {
                "name": "FO Supervisor",
                "login": "supervisor_restricted_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_fo_supervisor").id)
                ],
            }
        )
        cls.accountant_user = cls.env["res.users"].create(
            {
                "name": "Hotel Accountant",
                "login": "accountant_restricted_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_accountant").id)
                ],
            }
        )

        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def _confirmed_folio(self, use_agency=False):
        reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "agency_id": self.agency.id if use_agency else False,
                "property_id": self.property.id,
                "room_id": self.room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": self.checkin,
                "checkout_date": self.checkin + timedelta(days=3),
            }
        )
        reservation.action_confirm()
        return reservation, reservation.folio_ids[0]

    def _route_to_agency(self, category=None):
        return self.env["hotel.folio.routing.rule"].create(
            {
                "name": "Services to Entity",
                "property_id": self.property.id,
                "category_id": (category or self.restaurant_categ).id,
                "routing_type": "agency",
            }
        )

    def _entity_ceiling(self, daily_limit, category=None, on_excess="block"):
        return self.env["hotel.entity.service.ceiling"].create(
            {
                "partner_id": self.agency.id,
                "category_id": category.id if category else False,
                "daily_limit": daily_limit,
                "on_excess": on_excess,
            }
        )

    def test_blocked_service_rejected(self):
        reservation, folio = self._confirmed_folio()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.minibar_categ.id,
                "restriction_type": "blocked",
            }
        )
        with self.assertRaises(UserError):
            folio.add_charge(self.soda)
        # Unrestricted category still works.
        line = folio.add_charge(self.dinner)
        self.assertEqual(line.amount, 40.0)

    def test_blocked_service_supervisor_override(self):
        reservation, folio = self._confirmed_folio()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.minibar_categ.id,
                "restriction_type": "blocked",
            }
        )
        action = folio.with_user(
            self.supervisor_user
        ).action_open_add_charge()
        wizard = (
            self.env["hotel.add.charge.wizard"]
            .with_user(self.supervisor_user)
            .with_context(action["context"])
            .create(
                {
                    "product_id": self.soda.id,
                    "quantity": 1.0,
                    "price_unit": self.soda.list_price,
                    "override_reason": "Manager approved minibar",
                }
            )
        )
        wizard.action_add_charge()
        line = folio.line_ids.filtered(
            lambda charge: charge.product_id == self.soda
            and charge.source_type == "manual"
        )
        self.assertEqual(len(line), 1)
        self.assertEqual(line.amount, 5.0)
        # Override must be logged in the chatter.
        override_messages = folio.message_ids.filtered(
            lambda m: "Manager approved minibar" in (m.body or "")
        )
        self.assertTrue(override_messages)

    def test_manual_ui_charge_cannot_bypass_blocked_category(self):
        reservation, folio = self._confirmed_folio()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.minibar_categ.id,
                "restriction_type": "blocked",
            }
        )
        direct_values = {
            "folio_id": folio.id,
            "product_id": self.soda.id,
            "name": self.soda.display_name,
            "qty": 1.0,
            "price_unit": self.soda.list_price,
            "payee_partner_id": self.guest.id,
        }
        with self.assertRaises(UserError):
            self.env["hotel.folio.line"].with_user(
                self.frontdesk_user
            ).create(direct_values)

        action = folio.with_user(
            self.frontdesk_user
        ).action_open_add_charge()
        wizard = (
            self.env["hotel.add.charge.wizard"]
            .with_user(self.frontdesk_user)
            .with_context(action["context"])
            .create(
                {
                    "product_id": self.soda.id,
                    "quantity": 1.0,
                    "price_unit": self.soda.list_price,
                }
            )
        )
        with self.assertRaises(UserError):
            wizard.action_add_charge()
        self.assertFalse(
            folio.line_ids.filtered(
                lambda charge: charge.product_id == self.soda
                and charge.source_type == "manual"
            )
        )

    def test_override_requires_supervisor(self):
        reservation, folio = self._confirmed_folio()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.minibar_categ.id,
                "restriction_type": "blocked",
            }
        )
        with self.assertRaises(UserError):
            folio.with_user(self.frontdesk_user).with_context(
                service_override_reason="I said so"
            ).add_charge(self.soda)

    def test_daily_limit(self):
        reservation, folio = self._confirmed_folio()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.restaurant_categ.id,
                "restriction_type": "limited",
                "daily_limit": 50.0,
            }
        )
        folio.add_charge(self.dinner)  # 40.0, within limit
        with self.assertRaises(UserError):
            folio.add_charge(self.dinner)  # would reach 80.0
        # Next day the counter resets.
        line = folio.add_charge(
            self.dinner, date=fields.Datetime.now() + timedelta(days=1)
        )
        self.assertEqual(line.amount, 40.0)

    def test_stay_limit(self):
        reservation, folio = self._confirmed_folio()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.restaurant_categ.id,
                "restriction_type": "limited",
                "stay_limit": 60.0,
            }
        )
        folio.add_charge(self.dinner)  # 40.0
        with self.assertRaises(UserError):
            # Different day does not help: stay limit is cumulative.
            folio.add_charge(
                self.dinner, date=fields.Datetime.now() + timedelta(days=1)
            )

    def test_entity_daily_ceiling(self):
        self.env["hotel.folio.routing.rule"].create(
            {
                "name": "Restaurant to Entity",
                "property_id": self.property.id,
                "category_id": self.restaurant_categ.id,
                "routing_type": "agency",
            }
        )
        ceiling = self.env["hotel.entity.service.ceiling"].create(
            {
                "partner_id": self.agency.id,
                "category_id": self.restaurant_categ.id,
                "daily_limit": 50.0,
            }
        )
        self.assertEqual(ceiling.on_excess, "block")
        reservation, folio = self._confirmed_folio(use_agency=True)
        line = folio.add_charge(self.dinner)  # 40.0 billed to entity
        self.assertEqual(line.payee_partner_id, self.agency)
        with self.assertRaises(UserError):
            folio.add_charge(self.dinner)  # 80.0 > 50.0 ceiling
        override_line = folio.with_user(self.supervisor_user).with_context(
            service_override_reason="Approved entity ceiling override"
        ).add_charge(self.dinner)
        self.assertEqual(override_line.payee_partner_id, self.agency)
        self.assertTrue(
            folio.message_ids.filtered(
                lambda message: "Approved entity ceiling override"
                in (message.body or "")
            )
        )

    def test_entity_global_ceiling(self):
        # Ceiling without category applies to every service.
        self.env["hotel.folio.routing.rule"].create(
            {
                "name": "Minibar to Entity",
                "property_id": self.property.id,
                "category_id": self.minibar_categ.id,
                "routing_type": "agency",
            }
        )
        self.env["hotel.entity.service.ceiling"].create(
            {
                "partner_id": self.agency.id,
                "daily_limit": 12.0,
            }
        )
        reservation, folio = self._confirmed_folio(use_agency=True)
        folio.add_charge(self.soda, qty=2.0)  # 10.0 billed to entity
        with self.assertRaises(UserError):
            folio.add_charge(self.soda)  # 15.0 > 12.0 ceiling

    def test_charge_guest_split_prorates_tax_and_rounding(self):
        self._route_to_agency()
        ceiling = self._entity_ceiling(
            15.0,
            category=self.restaurant_categ,
            on_excess="charge_guest",
        )
        tax = self.env["account.tax"].create(
            {
                "name": "Restricted Service VAT 10%",
                "amount": 10.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "company_id": self.property.company_id.id,
            }
        )
        _reservation, folio = self._confirmed_folio(use_agency=True)
        consumed = folio.add_charge(
            self.dinner, price_unit=5.0, tax_ids=tax.ids
        )

        split = folio.add_charge(
            self.dinner, price_unit=10.01, tax_ids=tax.ids
        )

        self.assertEqual(len(split), 2)
        entity_line = split.filtered(
            lambda line: line.payee_partner_id == self.agency
        )
        guest_line = split.filtered(
            lambda line: line.payee_partner_id == self.guest
        )
        currency = folio.currency_id
        expected = tax.compute_all(
            10.01,
            currency=currency,
            quantity=1.0,
            product=self.dinner,
            partner=self.guest,
        )
        expected_entity = currency.round(ceiling.daily_limit - consumed.amount_total)
        expected_guest = currency.round(
            expected["total_included"] - expected_entity
        )
        self.assertEqual(
            currency.compare_amounts(entity_line.amount_total, expected_entity), 0
        )
        self.assertEqual(
            currency.compare_amounts(guest_line.amount_total, expected_guest), 0
        )
        self.assertEqual(
            currency.compare_amounts(
                sum(split.mapped("amount_total")), expected["total_included"]
            ),
            0,
        )
        self.assertEqual(
            currency.compare_amounts(
                sum(split.mapped("amount_untaxed")), expected["total_excluded"]
            ),
            0,
        )
        self.assertEqual(
            currency.compare_amounts(
                sum(split.mapped("amount_tax")),
                expected["total_included"] - expected["total_excluded"],
            ),
            0,
        )
        self.assertAlmostEqual(sum(split.mapped("qty")), 1.0, places=6)
        self.assertTrue(
            folio.message_ids.filtered(
                lambda message: ceiling.display_name in (message.body or "")
                and self.dinner.display_name in (message.body or "")
            )
        )

    def test_charge_guest_routes_full_charge_when_ceiling_consumed(self):
        self._route_to_agency()
        self._entity_ceiling(
            40.0,
            category=self.restaurant_categ,
            on_excess="charge_guest",
        )
        _reservation, folio = self._confirmed_folio(use_agency=True)
        first = folio.add_charge(self.dinner)
        self.assertEqual(first.payee_partner_id, self.agency)

        rerouted = folio.add_charge(self.dinner)

        self.assertEqual(len(rerouted), 1)
        self.assertEqual(rerouted.payee_partner_id, self.guest)
        self.assertEqual(rerouted.amount_total, 40.0)

    def test_charge_guest_global_ceiling_splits_all_services(self):
        self._route_to_agency(category=self.minibar_categ)
        self._entity_ceiling(12.0, on_excess="charge_guest")
        _reservation, folio = self._confirmed_folio(use_agency=True)

        split = folio.add_charge(self.soda, qty=3.0)

        entity_line = split.filtered(
            lambda line: line.payee_partner_id == self.agency
        )
        guest_line = split.filtered(
            lambda line: line.payee_partner_id == self.guest
        )
        self.assertEqual(entity_line.amount_total, 12.0)
        self.assertEqual(guest_line.amount_total, 3.0)

    def test_workflow_split_is_idempotent(self):
        self._route_to_agency()
        self._entity_ceiling(
            10.0,
            category=self.restaurant_categ,
            on_excess="charge_guest",
        )
        _reservation, folio = self._confirmed_folio(use_agency=True)
        values = {
            "source_type": "service",
            "source_reference": "SVC-SPLIT",
            "source_key": "service:ceiling-split",
        }

        first = folio._add_workflow_charge(self.dinner, **values)
        replay = folio._add_workflow_charge(self.dinner, **values)

        self.assertEqual(len(first), 2)
        self.assertEqual(replay, first)
        self.assertEqual(
            set(first.mapped("source_key")),
            {"service:ceiling-split", "service:ceiling-split:guest"},
        )
        self.assertEqual(
            self.env["hotel.folio.line"].search_count(
                [
                    (
                        "source_key",
                        "in",
                        [
                            "service:ceiling-split",
                            "service:ceiling-split:guest",
                        ],
                    )
                ]
            ),
            2,
        )

    def test_split_lines_invoice_by_payee(self):
        self._route_to_agency()
        self._entity_ceiling(
            15.0,
            category=self.restaurant_categ,
            on_excess="charge_guest",
        )
        _reservation, folio = self._confirmed_folio(use_agency=True)
        split = folio.add_charge(self.dinner)
        entity_line = split.filtered(
            lambda line: line.payee_partner_id == self.agency
        )
        guest_line = split.filtered(
            lambda line: line.payee_partner_id == self.guest
        )

        entity_action = folio.with_user(self.accountant_user).action_create_invoice(
            partner_id=self.agency.id
        )
        guest_action = folio.with_user(self.accountant_user).action_create_invoice(
            partner_id=self.guest.id
        )
        entity_invoice = self.env["account.move"].browse(entity_action["res_id"])
        guest_invoice = self.env["account.move"].browse(guest_action["res_id"])

        self.assertEqual(entity_invoice.partner_id, self.agency)
        self.assertEqual(guest_invoice.partner_id, self.guest)
        self.assertEqual(entity_line.invoice_line_id.move_id, entity_invoice)
        self.assertEqual(guest_line.invoice_line_id.move_id, guest_invoice)
        self.assertEqual(entity_invoice.amount_total, 15.0)
        self.assertEqual(guest_line.invoice_line_id.price_total, 25.0)
