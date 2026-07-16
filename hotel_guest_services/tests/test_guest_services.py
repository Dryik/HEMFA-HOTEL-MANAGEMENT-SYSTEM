from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelGuestServices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Guest Services Floor", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Guest Services Room",
                "base_price": 100.0,
                "property_id": cls.property.id,
            }
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

    def test_wakeup_urgency_is_searchable(self):
        now = fields.Datetime.now()
        overdue = self.env["hotel.wakeup.call"].create(
            {
                "property_id": self.property.id,
                "reservation_id": self.reservation.id,
                "scheduled_at": now - timedelta(minutes=5),
            }
        )
        upcoming = self.env["hotel.wakeup.call"].create(
            {
                "property_id": self.property.id,
                "reservation_id": self.reservation.id,
                "scheduled_at": now + timedelta(minutes=30),
            }
        )
        later = self.env["hotel.wakeup.call"].create(
            {
                "property_id": self.property.id,
                "reservation_id": self.reservation.id,
                "scheduled_at": now + timedelta(hours=2),
            }
        )

        self.assertEqual(overdue.urgency, "overdue")
        self.assertEqual(upcoming.urgency, "upcoming")
        self.assertEqual(later.urgency, "later")
        overdue_calls = self.env["hotel.wakeup.call"].search(
            [("urgency", "=", "overdue")]
        )
        self.assertIn(overdue, overdue_calls)
        self.assertNotIn(upcoming, overdue_calls)

    def test_wakeup_today_bounds_use_property_timezone(self):
        self.property.timezone = "Pacific/Kiritimati"
        calls = self.env["hotel.wakeup.call"].with_context(
            hotel_property_id=self.property.id
        )
        start, end = calls._property_calendar_day_bounds(
            self.property,
            datetime(2026, 7, 13, 11, 0),
        )
        self.assertEqual(start, datetime(2026, 7, 13, 10, 0))
        self.assertEqual(end, datetime(2026, 7, 14, 10, 0))

    def test_paid_and_free_services_keep_operational_and_financial_history(self):
        paid = self.env["hotel.service"].create(
            {
                "name": "Airport Transfer",
                "property_id": self.property.id,
                "default_price": 75.0,
                "charge_policy": "paid",
            }
        )
        free = self.env["hotel.service"].create(
            {
                "name": "Welcome Drink",
                "property_id": self.property.id,
                "charge_policy": "free",
            }
        )
        paid_delivery = self.env["hotel.reservation.service"].create(
            {
                "reservation_id": self.reservation.id,
                "service_id": paid.id,
                "quantity": 2,
            }
        )
        paid_delivery.action_confirm()
        paid_delivery.action_done()
        self.assertEqual(paid_delivery.state, "done")
        self.assertEqual(paid_delivery.folio_line_id.amount_untaxed, 150.0)
        self.assertEqual(paid_delivery.folio_line_id.source_type, "service")

        free_delivery = self.env["hotel.reservation.service"].create(
            {
                "reservation_id": self.reservation.id,
                "service_id": free.id,
            }
        )
        free_delivery.action_confirm()
        free_delivery.action_done()
        self.assertEqual(free_delivery.state, "done")
        self.assertFalse(free_delivery.folio_line_id)
        with self.assertRaises(UserError):
            paid_delivery.write({"quantity": 3})

    def test_reservation_documents_are_private_and_verified_by_workflow(self):
        document_type = self.env["hotel.document.type"].create(
            {"name": "Passport", "property_id": self.property.id}
        )
        attachment = self.env["ir.attachment"].create(
            {
                "name": "passport.pdf",
                "datas": "dGVzdA==",
                "mimetype": "application/pdf",
                "public": True,
            }
        )
        document = self.env["hotel.reservation.document"].create(
            {
                "reservation_id": self.reservation.id,
                "document_type_id": document_type.id,
                "attachment_id": attachment.id,
            }
        )
        self.assertFalse(attachment.public)
        self.assertEqual(attachment.res_model, document._name)
        self.assertEqual(attachment.res_id, document.id)
        document.action_verify()
        self.assertTrue(document.verified)
        self.assertEqual(document.verified_by_id, self.env.user)
        with self.assertRaises(UserError):
            document.write({"verified": False})

    def test_post_checkout_rating_is_single_use_and_manager_moderated(self):
        self.reservation.checkout_balance_override_reason = "Guest will settle later"
        self.reservation.action_check_out()
        rating = self.reservation.rating_ids
        self.assertEqual(len(rating), 1)
        rating._submit_public_feedback(
            {
                "rating": 5,
                "cleanliness_rating": 4,
                "service_rating": 5,
                "value_rating": 4,
                "comments": "Excellent stay",
            }
        )
        self.assertEqual(rating.state, "submitted")
        rating.action_approve()
        self.assertEqual(rating.state, "approved")
        with self.assertRaises(UserError):
            rating._submit_public_feedback({"rating": 1})
