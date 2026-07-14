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
            {
                "name": "Report Suite",
                "base_price": 150.0,
                "property_id": cls.property.id,
            }
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
            [{"name": f"Report Guest {i}", "is_hotel_guest": True} for i in range(1, 4)]
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
            }
        )
        cls.frontdesk = cls.env["res.users"].create(
            {
                "name": "Report Front Desk",
                "login": "report_frontdesk",
                "group_ids": [(4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)],
            }
        )
        cls.accountant = cls.env["res.users"].create(
            {
                "name": "Report Accountant",
                "login": "report_accountant",
                "group_ids": [(4, cls.env.ref("hotel_base.group_hotel_accountant").id)],
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
        future = self._reservation(self.rooms[1], self.guests[1], offset_days=1)
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
        self.assertEqual(action["report_name"], "hotel_reports.report_daily_movement")

    def test_print_dispatches_to_report_family_and_paper_format(self):
        cases = {
            "arrivals": (
                "hotel_reports.report_daily_movement",
                "Portrait",
                "operations",
            ),
            "security": (
                "hotel_reports.report_landscape_detail",
                "Landscape",
                "landscape",
            ),
        }
        for report_type, (report_name, orientation, family) in cases.items():
            wizard = self._wizard(report_type)
            action = wizard.action_print()
            report = self.env["ir.actions.report"]._get_report_from_name(report_name)
            payload = wizard._get_report_payload()
            self.assertEqual(action["report_name"], report_name)
            self.assertEqual(report.paperformat_id.orientation, orientation)
            self.assertEqual(payload["family"], family)
            self.assertEqual(
                round(sum(payload["column_widths"].values())),
                100,
            )

    def test_renderer_values(self):
        reservation = self._reservation(self.rooms[0], self.guests[0])
        reservation.action_confirm()
        wizard = self._wizard("arrivals")
        values = self.env[
            "report.hotel_reports.report_daily_movement"
        ]._get_report_values(wizard.ids)
        self.assertEqual(
            values["payloads"][wizard.id]["rows"][0]["reservation"],
            reservation.name,
        )

    def test_housekeeper_can_render_discrepancy_without_reservation_access(self):
        discrepancy = self._wizard("discrepancy")
        values = (
            self.env["report.hotel_reports.report_daily_movement"]
            .with_user(self.housekeeper)
            ._get_report_values(discrepancy.ids)
        )
        self.assertEqual(
            values["payloads"][discrepancy.id]["title"], "Housekeeping Discrepancy"
        )

    def test_movement_datetimes_use_the_property_timezone(self):
        reservation = self._reservation(self.rooms[0], self.guests[0])
        reservation.action_confirm()
        wizard = self._wizard("arrivals")
        expected = fields.Datetime.context_timestamp(
            wizard.with_context(tz=self.property.timezone),
            reservation.checkin_date,
        ).strftime("%d/%m/%Y %H:%M")
        payload = wizard._get_report_payload()
        self.assertEqual(payload["rows"][0]["arrival"], expected)

    def test_accountant_finance_reports_use_property_scoped_safe_sources(self):
        agency = self.env["res.partner"].create(
            {
                "name": "Report Agency",
                "is_hotel_agency": True,
            }
        )
        payment = self.env["account.payment"].create(
            {
                "amount": 40.0,
                "date": fields.Date.today(),
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": agency.id,
                "currency_id": self.property.company_id.currency_id.id,
                "hotel_property_id": self.property.id,
                "hotel_payment_purpose": "agency_advance",
            }
        )
        payment.action_post()

        reservation = self._reservation(self.rooms[0], self.guests[0])
        reservation.action_confirm()
        folio = reservation.folio_ids[0]
        product = self.env["product.product"].create(
            {
                "name": "Report POS Charge",
                "type": "service",
                "list_price": 18.0,
                "taxes_id": [(6, 0, [])],
            }
        )
        line = folio._add_workflow_charge(
            product,
            price_unit=18.0,
            date=self.today_noon,
            source_type="pos",
            source_reference="POS/SAFE/001",
            source_key="report-pos-safe-001",
        )

        advance_payload = (
            self._wizard("agency_advances")
            .with_user(self.accountant)
            ._get_report_payload()
        )
        advance_row = next(
            row for row in advance_payload["rows"] if row["payment"] == payment.name
        )
        self.assertEqual(advance_row["agency"], agency.name)

        pos_payload = (
            self._wizard("pos_room_charges")
            .with_user(self.accountant)
            ._get_report_payload()
        )
        pos_row = next(
            row for row in pos_payload["rows"] if row["description"] == line.name
        )
        self.assertEqual(pos_row["pos_receipt"], "POS/SAFE/001")

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
