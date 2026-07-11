from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelReservation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Res Test Hotel", "code": "RTH"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor R1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Res Double", "base_price": 200.0}
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "R101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "Test Guest", "is_hotel_guest": True}
        )
        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def _reservation(self, offset_days=0, nights=2, room=None, state="draft"):
        checkin = self.checkin + timedelta(days=offset_days)
        return self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "property_id": self.property.id,
                "room_id": (room or self.room).id,
                "room_type_id": self.room_type.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=nights),
                "state": state,
            }
        )

    def test_sequence_assigned(self):
        res = self._reservation()
        self.assertNotEqual(res.name, "New")
        self.assertTrue(res.name.isdigit())

    def test_nights_and_amount(self):
        res = self._reservation(nights=3)
        self.assertEqual(res.nights, 3)
        self.assertEqual(res.rate_night, 200.0)
        self.assertEqual(res.amount_total, 600.0)

    def test_overlap_rejected(self):
        self._reservation(state="confirmed")
        with self.assertRaises(ValidationError):
            self._reservation(offset_days=1, state="confirmed")

    def test_non_overlapping_ok(self):
        self._reservation(state="confirmed", nights=2)
        res2 = self._reservation(offset_days=2, state="confirmed")
        self.assertEqual(res2.state, "confirmed")

    def test_lifecycle_updates_room(self):
        res = self._reservation()
        res.action_confirm()
        self.assertEqual(self.room.occupancy_state, "reserved")
        res.action_check_in()
        self.assertEqual(self.room.occupancy_state, "occupied")
        res.action_check_out()
        self.assertEqual(self.room.occupancy_state, "checkout")
        self.assertEqual(self.room.hk_status, "dirty")

    def test_cancel_releases_room(self):
        res = self._reservation()
        res.action_confirm()
        self.assertEqual(self.room.occupancy_state, "reserved")
        res.action_cancel()
        self.assertEqual(res.state, "cancelled")
        self.assertEqual(self.room.occupancy_state, "vacant")

    def test_out_of_order_room_rejected(self):
        self.room.out_of_order = True
        with self.assertRaises(ValidationError):
            self._reservation(state="confirmed")

    def test_dashboard_data(self):
        res = self._reservation()
        res.action_confirm()
        res.action_check_in()
        data = self.env["hotel.reservation"].get_dashboard_data()
        self.assertGreaterEqual(data["in_house"], 1)
        self.assertGreaterEqual(data["occupied"], 1)
        self.assertIn("occupancy_pct", data)

    def test_reservation_unlink_restricted(self):
        res = self._reservation(state="confirmed")
        with self.assertRaises(UserError):
            res.unlink()

        res_draft = self._reservation(state="draft")
        # Should succeed
        res_draft.unlink()

    def test_room_unlink_restricted(self):
        self._reservation(state="confirmed")
        with self.assertRaises(UserError):
            self.room.unlink()

    def test_property_unlink_restricted(self):
        self._reservation(state="confirmed")
        with self.assertRaises(UserError):
            self.property.unlink()

