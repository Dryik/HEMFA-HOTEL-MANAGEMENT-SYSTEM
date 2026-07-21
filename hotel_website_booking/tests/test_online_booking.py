from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelOnlineBooking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.property.write(
            {
                "online_payment_policy": "manual",
                "website_description": "Online test hotel",
                "website_policy": "Online test policies",
            }
        )
        cls.website = cls.env["website"].search(
            [("company_id", "=", cls.property.company_id.id)], limit=1
        )
        cls.property.website_id = cls.website
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Online Booking Floor", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Online Suite",
                "property_id": cls.property.id,
                "base_price": 180.0,
                "website_published": True,
                "capacity_adults": 2,
            }
        )
        cls.env["hotel.document.type"].create(
            {
                "name": "Online Test Passport",
                "property_id": cls.property.id,
                "required_for_website": True,
            }
        )
        cls.rooms = cls.env["hotel.room"]
        for number in ("WEB-101", "WEB-102"):
            cls.rooms |= cls.env["hotel.room"].create(
                {
                    "name": number,
                    "floor_id": cls.floor.id,
                    "room_type_id": cls.room_type.id,
                    "website_published": True,
                }
            )
        cls.guest = cls.env["res.partner"].create(
            {
                "name": "Online Guest",
                "email": "online.guest@example.com",
                "is_hotel_guest": True,
                "company_id": cls.property.company_id.id,
            }
        )
        cls.pricelist = cls.env["product.pricelist"].create(
            {
                "name": "Online Hotel Pricelist",
                "currency_id": cls.property.company_id.currency_id.id,
                "company_id": cls.property.company_id.id,
                "hotel_website_published": True,
            }
        )
        cls.property.website_published = True
        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) + timedelta(days=10)

    def _booking(self, quantity=1):
        return self.env["hotel.online.booking"].create(
            {
                "website_id": self.website.id,
                "property_id": self.property.id,
                "partner_id": self.guest.id,
                "checkin_date": self.checkin,
                "checkout_date": self.checkin + timedelta(days=2),
                "pricelist_id": self.pricelist.id,
                "currency_id": self.pricelist.currency_id.id,
                "line_ids": [
                    Command.create(
                        {
                            "room_type_id": self.room_type.id,
                            "quantity": quantity,
                            "adults": 1,
                        }
                    )
                ],
            }
        )

    def _successful_transaction(self, booking, reference="WEB-TX"):
        return self.env["payment.transaction"].new(
            {
                "reference": reference,
                "amount": booking.amount_due_online,
                "currency_id": booking.currency_id.id,
                "partner_id": booking.partner_id.id,
                "hotel_online_booking_id": booking.id,
                "state": "done",
            }
        )

    def test_manual_request_is_non_blocking_until_approval(self):
        booking = self._booking(quantity=2)
        booking.action_submit()
        self.assertEqual(booking.state, "pending_review")
        self.assertFalse(booking.reservation_ids)

        booking.action_approve_manual()
        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(len(booking.reservation_ids), 2)
        self.assertEqual(len(booking.reservation_ids.mapped("room_id")), 2)
        self.assertTrue(all(booking.reservation_ids.mapped("rate_locked")))
        self.assertEqual(len(booking.reservation_ids.mapped("rate_line_ids")), 4)

    def test_paid_policy_creates_blocking_expiring_holds(self):
        self.property.write(
            {"online_payment_policy": "fixed_deposit", "online_deposit_value": 50.0}
        )
        booking = self._booking()
        booking.action_submit()

        self.assertEqual(booking.state, "payment_pending")
        self.assertEqual(booking.amount_due_online, 50.0)
        self.assertTrue(booking.expires_at)
        self.assertEqual(booking.reservation_ids.state, "pending_payment")
        self.assertTrue(booking.reservation_ids.rate_line_ids)

    def test_overlapping_multi_room_hold_is_atomic(self):
        self.property.write(
            {"online_payment_policy": "fixed_deposit", "online_deposit_value": 20.0}
        )
        first = self._booking(quantity=2)
        first.action_submit()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._booking().action_submit()
        self.assertEqual(len(first.reservation_ids), 2)
        self.assertEqual(set(first.reservation_ids.mapped("state")), {"pending_payment"})

    def test_expired_hold_releases_inventory(self):
        self.property.write(
            {"online_payment_policy": "full", "online_deposit_value": 0.0}
        )
        booking = self._booking()
        booking.action_submit()
        booking._expire_hold()
        self.assertEqual(booking.state, "expired")
        self.assertEqual(booking.reservation_ids.state, "cancelled")
        available = self.env["hotel.availability.service"].get_available_rooms(
            self.property.id,
            booking.checkin_date,
            booking.checkout_date,
            self.room_type.id,
        )
        self.assertEqual(len(available), 2)

    def test_unpublished_physical_rooms_are_not_allocated_online(self):
        self.rooms.write({"website_published": False})
        booking = self._booking()
        booking.action_submit()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            booking.action_approve_manual()
        self.assertFalse(booking.reservation_ids)

    def test_success_callback_is_idempotent(self):
        self.property.write(
            {"online_payment_policy": "fixed_deposit", "online_deposit_value": 50.0}
        )
        booking = self._booking()
        booking.action_submit()
        transaction = self._successful_transaction(booking)

        self.assertTrue(booking._confirm_paid_transaction(transaction))
        reservation_ids = booking.reservation_ids.ids
        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(set(booking.reservation_ids.mapped("state")), {"confirmed"})

        self.assertTrue(booking._confirm_paid_transaction(transaction))
        self.assertEqual(booking.reservation_ids.ids, reservation_ids)

    def test_late_payment_never_recreates_expired_inventory(self):
        self.property.write(
            {"online_payment_policy": "fixed_deposit", "online_deposit_value": 50.0}
        )
        booking = self._booking()
        booking.action_submit()
        transaction = self._successful_transaction(booking, reference="LATE-WEB-TX")
        reservation_ids = booking.reservation_ids.ids
        booking._expire_hold()

        self.assertFalse(booking._confirm_paid_transaction(transaction))
        self.assertEqual(booking.state, "payment_exception")
        self.assertEqual(booking.reservation_ids.ids, reservation_ids)
        self.assertEqual(set(booking.reservation_ids.mapped("state")), {"cancelled"})
        self.assertEqual(len(booking.activity_ids), 1)

        self.assertFalse(booking._confirm_paid_transaction(transaction))
        self.assertEqual(len(booking.activity_ids), 1)

    def test_payment_exception_returns_to_review(self):
        self.property.write(
            {"online_payment_policy": "fixed_deposit", "online_deposit_value": 50.0}
        )
        booking = self._booking()
        booking.action_submit()
        booking._expire_hold(payment_exception=True)
        self.assertEqual(booking.state, "payment_exception")

        booking.action_return_to_review()
        self.assertEqual(booking.state, "pending_review")
        self.assertFalse(booking.exception_note)
        self.assertFalse(
            booking.reservation_ids.filtered(
                lambda reservation: reservation.state == "pending_payment"
            )
        )
        with self.assertRaises(UserError):
            booking.action_return_to_review()

    def test_payment_exception_can_be_cancelled(self):
        self.property.write(
            {"online_payment_policy": "fixed_deposit", "online_deposit_value": 50.0}
        )
        booking = self._booking()
        booking.action_submit()
        booking._expire_hold(payment_exception=True)
        self.assertEqual(booking.state, "payment_exception")

        booking.action_cancel_online()
        self.assertEqual(booking.state, "cancelled")

    def test_quote_snapshots_are_per_night_and_tax_ready(self):
        booking = self._booking()
        booking.action_reprice()
        self.assertEqual(len(booking.line_ids.quote_snapshot["nights"]), 2)
        self.assertEqual(
            len(booking.quote_snapshot["rooms"][0]["rule_trace"]), 2
        )
        self.assertEqual(booking.amount_untaxed, 360.0)
        self.assertGreaterEqual(booking.amount_total, booking.amount_untaxed)
