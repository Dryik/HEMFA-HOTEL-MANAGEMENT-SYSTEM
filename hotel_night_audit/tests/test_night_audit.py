from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelNightAudit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {
                "name": "Audit Test Hotel",
                "code": "ATH",
                "current_business_date": fields.Date.today(),
            }
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor A1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Audit Double Room", "base_price": 180.0}
        )
        cls.room1 = cls.env["hotel.room"].create(
            {
                "name": "R301",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.room2 = cls.env["hotel.room"].create(
            {
                "name": "R302",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "Audit Guest", "is_hotel_guest": True}
        )

        cls.business_date = cls.property.current_business_date
        cls.checkin = fields.Datetime.to_datetime(cls.business_date).replace(
            hour=12, minute=0, second=0
        )

    def _reservation(self, room, partner=None, offset_days=0, nights=2, state="draft"):
        checkin = self.checkin + timedelta(days=offset_days)
        return self.env["hotel.reservation"].create(
            {
                "partner_id": (partner or self.guest).id,
                "property_id": self.property.id,
                "room_id": room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=nights),
                "state": state,
            }
        )

    def test_night_audit_rollover(self):
        # 1. Create a stay that is checked in
        res_checked_in = self._reservation(self.room1)
        res_checked_in.action_confirm()
        res_checked_in.action_check_in()
        self.assertEqual(res_checked_in.state, "checked_in")

        # 2. Create a stay that is confirmed but never arrived (no-show)
        res_no_show = self._reservation(self.room2, offset_days=0, state="confirmed")

        # 3. Initialize night audit
        audit = self.env["hotel.night.audit"].create(
            {
                "property_id": self.property.id,
            }
        )
        self.assertEqual(audit.date, self.business_date)
        self.assertEqual(audit.state, "draft")

        # 4. Run night audit
        audit.action_run_audit()

        # 5. Assertions
        # Check audit values
        self.assertEqual(audit.state, "done")
        self.assertEqual(audit.revenue_posted, 180.0) # room1 charge
        self.assertEqual(audit.occupancy_pct, 50.0) # 1 room occupied of 2 sellable

        # Check checked-in folio room charge line
        folio = res_checked_in.folio_ids[0]
        self.assertEqual(len(folio.line_ids), 1)
        room_charge = folio.line_ids[0]
        self.assertEqual(room_charge.amount, 180.0)
        self.assertEqual(room_charge.name, f"Room Charge - {self.business_date}")
        self.assertTrue(room_charge.is_posted)

        # Check no-show status
        self.assertEqual(res_no_show.state, "no_show")

        # Check rolled business date
        self.assertEqual(self.property.current_business_date, self.business_date + timedelta(days=1))

    def test_night_audit_already_charged_skipped(self):
        res_checked_in = self._reservation(self.room1)
        res_checked_in.action_confirm()
        res_checked_in.action_check_in()

        # Run first audit
        audit1 = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        audit1.action_run_audit()

        # Create a second audit for the same day (force same date to test skip, usually property rolls date, so we'll mock it)
        # Roll back business date on property to re-run for same date
        self.property.current_business_date = self.business_date
        audit2 = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        
        audit2.action_run_audit()
        # Should not charge again
        self.assertEqual(audit2.revenue_posted, 0.0)
        
        # Verify folio has only 1 charge
        folio = res_checked_in.folio_ids[0]
        self.assertEqual(len(folio.line_ids), 1)

    def test_night_audit_unlink_restricted(self):
        audit = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        audit.action_run_audit()
        self.assertEqual(audit.state, "done")
        with self.assertRaises(UserError):
            audit.unlink()

        audit_draft = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        self.assertEqual(audit_draft.state, "draft")
        audit_draft.unlink()

