from datetime import timedelta
from pathlib import Path
from runpy import run_path

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelReservation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor R1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Res Double",
                "base_price": 200.0,
                "property_id": cls.property.id,
            }
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "R101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.room_2 = cls.env["hotel.room"].create(
            {
                "name": "R102",
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
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Reservation Test Manager",
                "login": "reservation_test_manager",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_manager").id)
                ],
            }
        )
        cls.frontdesk_user = cls.env["res.users"].create(
            {
                "name": "Reservation Test Front Desk",
                "login": "reservation_test_frontdesk",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)
                ],
            }
        )
        cls.housekeeper = cls.env["res.users"].create(
            {
                "name": "Reservation Security Housekeeper",
                "login": "reservation_security_housekeeper",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_housekeeping").id)
                ],
            }
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
        # Future bookings are date-based inventory and do not change physical occupancy.
        self.assertEqual(self.room.occupancy_state, "vacant")
        res.action_check_in()
        self.assertEqual(self.room.occupancy_state, "occupied")
        res.checkout_balance_override_reason = "Reservation lifecycle test"
        res.with_user(self.manager).action_check_out()
        self.assertEqual(self.room.occupancy_state, "checkout")
        self.assertEqual(self.room.hk_status, "dirty")

    def test_cancel_releases_room(self):
        res = self._reservation()
        res.action_confirm()
        self.assertEqual(self.room.occupancy_state, "vacant")
        res.action_cancel()
        self.assertEqual(res.state, "cancelled")
        self.assertTrue(res.cancelled_at)
        self.assertEqual(self.room.occupancy_state, "vacant")
        with self.assertRaises(UserError):
            res.write({"cancelled_at": fields.Datetime.now()})
        res.action_reset_draft()
        self.assertFalse(res.cancelled_at)

    def test_expired_payment_hold_records_cancellation_time(self):
        reservation = self._reservation()
        reservation._action_hold_for_payment(fields.Datetime.now())
        reservation._action_expire_payment_hold()
        self.assertEqual(reservation.state, "cancelled")
        self.assertTrue(reservation.cancelled_at)
        self.assertFalse(reservation.hold_expires_at)

    def test_cancellation_migration_backfills_existing_cancelled_records(self):
        reservation = self._reservation()
        reservation.action_cancel()
        self.env.cr.execute(
            "UPDATE hotel_reservation SET cancelled_at = NULL WHERE id = %s",
            [reservation.id],
        )
        reservation.invalidate_recordset(["cancelled_at"])
        self.assertFalse(reservation.cancelled_at)

        migration_path = (
            Path(__file__).parents[1]
            / "migrations"
            / "19.0.6.0.0"
            / "post-migrate.py"
        )
        run_path(str(migration_path))["migrate"](self.env.cr, "19.0.6.0.0")
        reservation.invalidate_recordset(["cancelled_at"])
        self.assertTrue(reservation.cancelled_at)

    def test_state_cannot_bypass_workflow(self):
        reservation = self._reservation()
        with self.assertRaises(UserError):
            reservation.write({"state": "checked_in"})
        with self.assertRaises(UserError):
            reservation.with_user(self.frontdesk_user).with_context(
                hotel_reservation_transition=True
            ).write({"state": "checked_in"})
        reservation.action_confirm()
        with self.assertRaises(UserError):
            reservation.write({"state": "draft"})
        with self.assertRaises(UserError):
            reservation.write({"actual_checkin": fields.Datetime.now()})
        reservation.action_cancel()
        with self.assertRaises(UserError):
            reservation.write({"room_id": self.room_2.id})

    def test_housekeeping_cannot_read_reservation_financials(self):
        reservation = self._reservation(state="confirmed")
        with self.assertRaises(AccessError):
            reservation.with_user(self.housekeeper).read(
                ["partner_id", "rate_night", "amount_total"]
            )

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

    def test_room_move_amendment_records_snapshots(self):
        reservation = self._reservation(state="confirmed")
        amendment = self.env["hotel.reservation.amendment"].with_user(
            self.manager
        ).create(
            {
                "reservation_id": reservation.id,
                "amendment_type": "room_move",
                "new_room_id": self.room_2.id,
                "reason": "Guest requested a quieter room",
            }
        )
        amendment.action_apply()
        self.assertEqual(reservation.room_id, self.room_2)
        self.assertEqual(amendment.state, "applied")
        self.assertEqual(amendment.before_values["room_id"], self.room.id)
        self.assertEqual(amendment.after_values["room_id"], self.room_2.id)
        with self.assertRaises(UserError):
            amendment.write({"reason": "Changed"})

    def test_group_partial_allocation_and_confirmation(self):
        group = self.env["hotel.reservation.group"].create(
            {
                "property_id": self.property.id,
                "group_partner_id": self.guest.id,
                "billing_partner_id": self.guest.id,
                "checkin_date": self.checkin,
                "checkout_date": self.checkin + timedelta(days=2),
                "allocation_line_ids": [
                    (
                        0,
                        0,
                        {
                            "room_type_id": self.room_type.id,
                            "requested_qty": 3,
                        },
                    )
                ],
            }
        )
        group.action_allocate_available()
        self.assertEqual(group.requested_room_count, 3)
        self.assertEqual(group.allocated_room_count, 2)
        group.action_confirm()
        self.assertEqual(group.state, "confirmed")
        self.assertTrue(all(member.state == "confirmed" for member in group.member_ids))
        with self.assertRaises(UserError):
            group.write({"state": "draft"})
        with self.assertRaises(UserError):
            group.allocation_line_ids.write({"requested_qty": 1})
