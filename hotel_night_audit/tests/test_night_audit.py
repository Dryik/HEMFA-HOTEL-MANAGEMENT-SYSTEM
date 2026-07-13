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
        cls.room_type.product_id.write({"taxes_id": [(6, 0, [])]})
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
        cls.frontdesk_user = cls.env["res.users"].create(
            {
                "name": "Audit Front Desk",
                "login": "audit_frontdesk_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )
        cls.supervisor_user = cls.env["res.users"].create(
            {
                "name": "Audit Supervisor",
                "login": "audit_supervisor_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_fo_supervisor").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )
        cls.manager_user = cls.env["res.users"].create(
            {
                "name": "Audit Manager",
                "login": "audit_manager_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_manager").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
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

    def _run_audit(self, audit):
        return audit.with_user(self.supervisor_user).action_run_audit()

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

        with self.assertRaises(UserError):
            audit.write({"state": "done"})
        with self.assertRaises(UserError):
            audit.with_context(hotel_audit_write=True).write({"state": "done"})

        # 4. Run night audit
        self._run_audit(audit)

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

        # The operational audit lock remains immutable, but an accountant can
        # still transfer the charge to the native draft invoice exactly once.
        invoice_action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(invoice_action["res_id"])
        self.assertEqual(room_charge.invoice_line_id.move_id, invoice)
        self.assertEqual(room_charge.lock_state, "accounting")

        # Check no-show status
        self.assertEqual(res_no_show.state, "no_show")

        # Check rolled business date
        self.assertEqual(self.property.current_business_date, self.business_date + timedelta(days=1))

        # Audit detail lines expose room and guest for the tape review.
        posted_line = audit.line_ids.filtered(lambda l: l.status == "posted")
        self.assertTrue(posted_line)
        self.assertEqual(posted_line.room_id, self.room1)
        self.assertEqual(posted_line.partner_id, self.guest)
        self.assertTrue(audit._fields.get("message_ids"))

    def test_night_audit_duplicate_rejected_and_reversal_reruns(self):
        res_checked_in = self._reservation(self.room1)
        res_checked_in.action_confirm()
        res_checked_in.action_check_in()

        # Run first audit
        audit1 = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        self._run_audit(audit1)

        # A second active audit for the same property/date is rejected.
        self.property._set_business_date(self.business_date)
        with self.assertRaises(UserError):
            self.env["hotel.night.audit"].create({"property_id": self.property.id})

        audit1.with_user(self.manager_user).action_reverse("Correction test")
        self.assertEqual(audit1.state, "reversed")
        audit2 = self.env["hotel.night.audit"].create(
            {"property_id": self.property.id}
        )
        self._run_audit(audit2)
        self.assertEqual(audit2.state, "done")

        # Original, exact reversal, and rerun are all retained.
        folio = res_checked_in.folio_ids[0]
        self.assertEqual(len(folio.line_ids), 3)
        self.assertEqual(sum(folio.line_ids.mapped("amount_total")), 180.0)

    def test_night_audit_unlink_restricted(self):
        audit = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        self._run_audit(audit)
        self.assertEqual(audit.state, "done")
        with self.assertRaises(UserError):
            audit.unlink()

        audit_draft = self.env["hotel.night.audit"].create({"property_id": self.property.id})
        self.assertEqual(audit_draft.state, "draft")
        audit_draft.unlink()

    def test_frontdesk_cannot_run_night_audit(self):
        audit = self.env["hotel.night.audit"].create(
            {"property_id": self.property.id}
        )
        with self.assertRaises(UserError):
            audit.with_user(self.frontdesk_user).action_run_audit()
        self.assertEqual(audit.state, "draft")

    def test_audit_identity_cannot_be_forged(self):
        with self.assertRaises(UserError):
            self.env["hotel.night.audit"].with_user(self.supervisor_user).create(
                {
                    "property_id": self.property.id,
                    "name": "FORGED-AUDIT",
                }
            )
