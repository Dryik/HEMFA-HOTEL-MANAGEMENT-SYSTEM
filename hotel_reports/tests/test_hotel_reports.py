from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelReports(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Report Test Hotel", "code": "RPH"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor RP1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Report Suite", "base_price": 150.0}
        )
        cls.rooms = cls.env["hotel.room"].create(
            [
                {
                    "name": f"RP10{i}",
                    "floor_id": cls.floor.id,
                    "room_type_id": cls.room_type.id,
                }
                for i in range(1, 4)
            ]
        )
        cls.guests = cls.env["res.partner"].create(
            [
                {"name": f"Report Guest {i}", "is_hotel_guest": True}
                for i in range(1, 4)
            ]
        )
        cls.today_noon = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        cls.housekeeper = cls.env["res.users"].create(
            {
                "name": "Report Housekeeper",
                "login": "report_housekeeper",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_housekeeping").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )
        cls.frontdesk = cls.env["res.users"].create(
            {
                "name": "Report Front Desk",
                "login": "report_frontdesk",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )

    def _reservation(self, room, guest, offset_days=0, nights=2):
        checkin = self.today_noon + timedelta(days=offset_days)
        return self.env["hotel.reservation"].create(
            {
                "partner_id": guest.id,
                "property_id": self.property.id,
                "room_id": room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=nights),
            }
        )

    def _wizard(self, report_type, date=None):
        return self.env["hotel.report.wizard"].create(
            {
                "report_type": report_type,
                "date": date or fields.Date.context_today(self.env.user),
                "property_id": self.property.id,
            }
        )

    def test_arrivals_report(self):
        arriving = self._reservation(self.rooms[0], self.guests[0])
        arriving.action_confirm()
        # Tomorrow's arrival must not appear today.
        future = self._reservation(
            self.rooms[1], self.guests[1], offset_days=1
        )
        future.action_confirm()

        wizard = self._wizard("arrivals")
        reservations = wizard._get_reservations()
        self.assertIn(arriving, reservations)
        self.assertNotIn(future, reservations)

    def test_departures_report(self):
        leaving_today = self._reservation(
            self.rooms[0], self.guests[0], offset_days=-2, nights=2
        )
        leaving_today.action_confirm()
        leaving_today.action_check_in()
        staying = self._reservation(
            self.rooms[1], self.guests[1], offset_days=-1, nights=5
        )
        staying.action_confirm()
        staying.action_check_in()

        wizard = self._wizard("departures")
        reservations = wizard._get_reservations()
        self.assertIn(leaving_today, reservations)
        self.assertNotIn(staying, reservations)

    def test_inhouse_and_security_reports(self):
        inhouse = self._reservation(self.rooms[0], self.guests[0])
        inhouse.action_confirm()
        inhouse.action_check_in()
        only_confirmed = self._reservation(self.rooms[1], self.guests[1])
        only_confirmed.action_confirm()

        for report_type in ("inhouse", "security"):
            wizard = self._wizard(report_type)
            reservations = wizard._get_reservations()
            self.assertIn(inhouse, reservations)
            self.assertNotIn(only_confirmed, reservations)

    def test_print_returns_report_action(self):
        wizard = self._wizard("arrivals")
        action = wizard.action_print()
        self.assertEqual(action["type"], "ir.actions.report")
        self.assertEqual(
            action["report_name"], "hotel_reports.report_daily_movement"
        )

    def test_renderer_values(self):
        reservation = self._reservation(self.rooms[0], self.guests[0])
        reservation.action_confirm()
        wizard = self._wizard("arrivals")
        values = self.env[
            "report.hotel_reports.report_daily_movement"
        ]._get_report_values(wizard.ids)
        self.assertIn(reservation, values["reservations_for"][wizard.id])

    def test_western_digits_preserve_zero(self):
        wizard = self._wizard("occupancy")
        self.assertEqual(wizard._western(0), "0")
        self.assertEqual(wizard._western("٢٠٢٦"), "2026")

    def test_xlsx_uses_same_payload(self):
        reservation = self._reservation(self.rooms[0], self.guests[0])
        reservation.action_confirm()
        wizard = self._wizard("arrivals")
        payload = wizard._get_report_payload()
        workbook = wizard._build_xlsx()
        self.assertTrue(payload["rows"])
        self.assertTrue(workbook.startswith(b"PK"))

    def test_report_types_are_role_restricted(self):
        discrepancy = self._wizard("discrepancy").with_user(self.housekeeper)
        discrepancy._get_report_payload()
        debtors = self._wizard("debtors").with_user(self.housekeeper)
        with self.assertRaises(UserError):
            debtors._get_report_payload()

    def test_consolidated_statement_pdf_xlsx_payload_has_balances(self):
        reservation = self._reservation(self.rooms[0], self.guests[0])
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        wizard = self.env["hotel.report.wizard"].create(
            {
                "report_type": "folio_statement",
                "date": fields.Date.context_today(self.env.user),
                "property_id": self.property.id,
                "folio_id": folio.id,
            }
        )
        payload = wizard._get_report_payload()
        self.assertEqual(len(payload["summary"]), 4)
        self.assertEqual(payload["summary"][-1][1], folio.amount_due)
        self.assertEqual(
            wizard.with_user(self.frontdesk)._get_report_payload()["summary"],
            payload["summary"],
        )
        self.assertTrue(wizard._build_xlsx().startswith(b"PK"))
