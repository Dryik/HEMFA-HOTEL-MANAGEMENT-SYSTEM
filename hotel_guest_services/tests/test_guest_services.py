from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelGuestServices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Guest Services Hotel", "code": "GSH"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Guest Services Floor", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Guest Services Room", "base_price": 100.0}
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "GS101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "Guest Services Guest", "is_hotel_guest": True}
        )
        checkin = fields.Datetime.now().replace(minute=0, second=0, microsecond=0)
        cls.reservation = cls.env["hotel.reservation"].create(
            {
                "partner_id": cls.guest.id,
                "property_id": cls.property.id,
                "room_type_id": cls.room_type.id,
                "room_id": cls.room.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=2),
            }
        )
        cls.reservation.action_confirm()
        cls.reservation.action_check_in()

    def test_lost_found_resolution_is_immutable(self):
        item = self.env["hotel.lost.found"].create(
            {
                "property_id": self.property.id,
                "room_id": self.room.id,
                "reservation_id": self.reservation.id,
                "item_name": "Wallet",
                "description": "Black wallet",
                "storage_location": "Front desk safe",
                "claimant_id": self.guest.id,
            }
        )
        item.action_mark_claimed()
        self.assertEqual(item.state, "claimed")
        with self.assertRaises(UserError):
            item.write({"storage_location": "Changed"})

    def test_dnd_end_is_immutable(self):
        request = self.env["hotel.do.not.disturb"].create(
            {
                "property_id": self.property.id,
                "reservation_id": self.reservation.id,
            }
        )
        with self.assertRaises(UserError):
            request.write({"state": "ended"})
        with self.assertRaises(UserError):
            request.with_context(hotel_guest_service_transition=True).write(
                {"state": "ended"}
            )
        request.action_end()
        self.assertEqual(request.state, "ended")
        self.assertGreater(request.end_at, request.start_at)
        with self.assertRaises(UserError):
            request.write({"note": "Changed"})

    def test_wakeup_completion_is_immutable(self):
        call = self.env["hotel.wakeup.call"].create(
            {
                "property_id": self.property.id,
                "reservation_id": self.reservation.id,
                "scheduled_at": fields.Datetime.now() + timedelta(hours=1),
            }
        )
        call.action_complete()
        self.assertEqual(call.state, "completed")
        with self.assertRaises(UserError):
            call.write({"completion_note": "Changed"})
