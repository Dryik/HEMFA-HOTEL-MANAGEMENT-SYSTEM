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
        line = folio.with_user(self.supervisor_user).with_context(
            service_override_reason="Manager approved minibar"
        ).add_charge(self.soda)
        self.assertEqual(line.amount, 5.0)
        # Override must be logged in the chatter.
        override_messages = folio.message_ids.filtered(
            lambda m: "Manager approved minibar" in (m.body or "")
        )
        self.assertTrue(override_messages)

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
        self.env["hotel.entity.service.ceiling"].create(
            {
                "partner_id": self.agency.id,
                "category_id": self.restaurant_categ.id,
                "daily_limit": 50.0,
            }
        )
        reservation, folio = self._confirmed_folio(use_agency=True)
        line = folio.add_charge(self.dinner)  # 40.0 billed to entity
        self.assertEqual(line.payee_partner_id, self.agency)
        with self.assertRaises(UserError):
            folio.add_charge(self.dinner)  # 80.0 > 50.0 ceiling

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
