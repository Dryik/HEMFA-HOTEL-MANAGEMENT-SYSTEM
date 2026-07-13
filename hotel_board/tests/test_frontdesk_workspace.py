from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelFrontdeskWorkspace(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.business_date = fields.Date.today()
        cls.property = cls.env["hotel.property"].create(
            {
                "name": "Workspace Hotel",
                "code": "WSH",
                "current_business_date": cls.business_date,
                "day_start_hour": 12.0,
                "timezone": "Africa/Tripoli",
            }
        )
        cls.floor = cls.env["hotel.floor"].create(
            {
                "name": "Workspace Floor",
                "sequence": 10,
                "property_id": cls.property.id,
            }
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Workspace Double",
                "code": "WSD",
                "property_id": cls.property.id,
                "base_price": 150.0,
            }
        )
        cls.room_reserved = cls._create_room("W101")
        cls.room_occupied = cls._create_room("W102")
        cls.room_empty = cls._create_room("W103")
        cls.room_dirty = cls._create_room("W104", hk_status="dirty")
        cls.guest = cls.env["res.partner"].create(
            {"name": "Workspace Guest", "is_hotel_guest": True}
        )
        cls.start, _end = cls.property.get_business_day_bounds(cls.business_date)
        cls.end, _end = cls.property.get_business_day_bounds(
            cls.business_date + timedelta(days=2)
        )
        cls.reserved = cls._create_reservation(cls.room_reserved)
        cls.reserved.action_confirm()
        cls.in_house = cls._create_reservation(cls.room_occupied)
        cls.in_house.action_confirm()
        cls.in_house.action_check_in()
        cls.workspace = cls.env["hotel.frontdesk.workspace"]

    @classmethod
    def _create_room(cls, name, hk_status="clean"):
        return cls.env["hotel.room"].create(
            {
                "name": name,
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
                "hk_status": hk_status,
            }
        )

    @classmethod
    def _create_reservation(cls, room):
        return cls.env["hotel.reservation"].create(
            {
                "partner_id": cls.guest.id,
                "property_id": cls.property.id,
                "room_type_id": cls.room_type.id,
                "room_id": room.id,
                "checkin_date": cls.start,
                "checkout_date": cls.end,
            }
        )

    def test_snapshot_groups_rooms_and_preserves_drilldown_domains(self):
        snapshot = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date
        )
        self.assertEqual(snapshot["version"], 1)
        self.assertEqual(snapshot["meta"]["property_id"], self.property.id)
        self.assertEqual(snapshot["meta"]["metric_mode"], "forecast")
        self.assertEqual(snapshot["kpis"]["reserved"]["value"], 1)
        self.assertEqual(snapshot["kpis"]["in_house"]["value"], 1)
        self.assertEqual(snapshot["kpis"]["vacant_clean"]["value"], 1)
        self.assertEqual(snapshot["kpis"]["vacant_dirty"]["value"], 1)
        self.assertEqual(len(snapshot["floors"]), 1)
        self.assertEqual(snapshot["floors"][0]["counts"]["total"], 4)
        self.assertEqual(snapshot["floors"][0]["counts"]["sellable"], 4)

        for key in (
            "arrivals",
            "departures",
            "in_house",
            "reserved",
            "vacant_clean",
            "vacant_dirty",
            "out_of_order",
            "house_use",
        ):
            kpi = snapshot["kpis"][key]
            action = kpi["action"]
            self.assertEqual(
                self.env[action["res_model"]].search_count(action["domain"]),
                kpi["value"],
                key,
            )
            self.assertEqual(
                action["context"]["hotel_business_date"],
                fields.Date.to_string(self.business_date),
            )

    def test_metric_modes_actual_forecast_and_unavailable(self):
        prior_date = self.business_date - timedelta(days=1)
        self.env["hotel.night.audit"].create(
            {
                "property_id": self.property.id,
                "date": prior_date,
                "state": "done",
                "occupancy_pct": 75.0,
                "adr": 120.0,
                "revpar": 90.0,
                "room_count": 4,
                "sellable_room_count": 4,
                "occupied_room_count": 3,
            }
        )
        actual = self.workspace.get_workspace_snapshot(self.property.id, prior_date)
        self.assertEqual(actual["meta"]["metric_mode"], "actual")
        self.assertEqual(actual["kpis"]["occupancy"]["value"], 75.0)
        self.assertEqual(actual["kpis"]["adr"]["value"], 120.0)
        self.assertEqual(actual["kpis"]["revpar"]["value"], 90.0)

        forecast = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date
        )
        self.assertEqual(forecast["meta"]["metric_mode"], "forecast")
        self.assertTrue(forecast["kpis"]["adr"]["available"])
        self.assertEqual(forecast["kpis"]["occupancy"]["value"], 50.0)
        self.assertEqual(forecast["kpis"]["adr"]["value"], 150.0)
        self.assertEqual(forecast["kpis"]["revpar"]["value"], 75.0)

        unaudited = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date - timedelta(days=2)
        )
        self.assertEqual(unaudited["meta"]["metric_mode"], "unavailable")
        self.assertFalse(unaudited["kpis"]["occupancy"]["available"])
        self.assertFalse(unaudited["kpis"]["occupancy"]["action"])

    def test_planning_includes_empty_rooms_and_actionable_cells(self):
        planning = self.workspace.get_planning_window(
            self.property.id, self.business_date, 14, {}
        )
        self.assertEqual(planning["meta"]["day_count"], 14)
        self.assertEqual(planning["totals"]["rooms"], 4)
        self.assertEqual(len(planning["days"]), 14)
        rows = {row["id"]: row for floor in planning["floors"] for row in floor["rows"]}
        self.assertIn(self.room_empty.id, rows)
        empty_first_day = rows[self.room_empty.id]["day_statuses"][0]
        self.assertEqual(empty_first_day["primary_status"], "vacant")
        self.assertEqual(
            empty_first_day["action"]["context"]["default_room_id"],
            self.room_empty.id,
        )
        reserved_row = rows[self.room_reserved.id]
        self.assertEqual(reserved_row["day_statuses"][0]["primary_status"], "reserved")
        self.assertEqual(reserved_row["reservations"][0]["span"], 2)
        self.assertEqual(
            reserved_row["reservations"][0]["action"]["context"]["hotel_business_date"],
            fields.Date.to_string(self.business_date),
        )

        self.env["hotel.do.not.disturb"].create(
            {
                "property_id": self.property.id,
                "reservation_id": self.in_house.id,
            }
        )
        maintenance = self.env["hotel.maintenance.request"].create(
            {
                "property_id": self.property.id,
                "room_id": self.room_empty.id,
                "description": "Planning blocker",
                "blocks_room": True,
            }
        )
        maintenance.action_confirm()
        alerted = self.workspace.get_planning_window(
            self.property.id, self.business_date, 7, {}
        )
        alerted_rows = {
            row["id"]: row for floor in alerted["floors"] for row in floor["rows"]
        }
        self.assertEqual(
            alerted_rows[self.room_empty.id]["capacity_blocker"], "out_of_order"
        )
        self.assertFalse(alerted_rows[self.room_empty.id]["day_statuses"][0]["action"])
        self.assertIn(
            "maintenance",
            {item["type"] for item in alerted_rows[self.room_empty.id]["alerts"]},
        )
        self.assertIn(
            "dnd",
            {item["type"] for item in alerted_rows[self.room_occupied.id]["alerts"]},
        )

        filtered = self.workspace.get_planning_window(
            self.property.id,
            self.business_date,
            7,
            {"room_query": self.room_empty.name},
        )
        self.assertEqual(filtered["totals"]["rooms"], 1)
        with self.assertRaises(ValidationError):
            self.workspace.get_planning_window(
                self.property.id, self.business_date, 31, {}
            )

    def test_non_current_stays_and_future_departures_are_date_relative(self):
        historical_date = self.business_date - timedelta(days=4)
        actual_start, actual_end = self.property.get_business_day_bounds(
            historical_date
        )
        historical_room = self._create_room("W105")
        historical = (
            self.env["hotel.reservation"]
            .sudo()
            .with_context(hotel_migration=True)
            .create(
                {
                    "partner_id": self.guest.id,
                    "property_id": self.property.id,
                    "room_type_id": self.room_type.id,
                    "room_id": historical_room.id,
                    "checkin_date": actual_start,
                    "checkout_date": actual_end,
                    "actual_checkin": actual_start,
                    "actual_checkout": actual_end,
                    "state": "checked_out",
                }
            )
        )
        historical_snapshot = self.workspace.get_workspace_snapshot(
            self.property.id, historical_date
        )
        historical_payload = next(
            room
            for floor in historical_snapshot["floors"]
            for room in floor["rooms"]
            if room["id"] == historical_room.id
        )
        self.assertEqual(historical_payload["reservation"]["id"], historical.id)
        self.assertEqual(historical_payload["primary_status"], "occupied")
        self.assertIn(
            historical.id,
            historical_snapshot["kpis"]["in_house"]["action"]["domain"][0][2],
        )

        checkout_snapshot = self.workspace.get_workspace_snapshot(
            self.property.id, historical_date + timedelta(days=1)
        )
        checkout_payload = next(
            room
            for floor in checkout_snapshot["floors"]
            for room in floor["rooms"]
            if room["id"] == historical_room.id
        )
        self.assertEqual(checkout_payload["reservation"]["id"], historical.id)
        self.assertEqual(checkout_payload["primary_status"], "checkout")

        future_departures = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date + timedelta(days=2)
        )
        self.assertEqual(future_departures["kpis"]["departures"]["value"], 2)
        departure_action = future_departures["kpis"]["departures"]["action"]
        self.assertEqual(
            self.env["hotel.reservation"].search_count(departure_action["domain"]),
            2,
        )
        departure_rooms = {
            room["id"]: room
            for floor in future_departures["floors"]
            for room in floor["rooms"]
        }
        self.assertEqual(
            departure_rooms[self.room_reserved.id]["reservation"]["id"],
            self.reserved.id,
        )
        self.assertEqual(
            departure_rooms[self.room_reserved.id]["primary_status"], "checkout"
        )
        self.assertEqual(
            departure_rooms[self.room_occupied.id]["reservation"]["id"],
            self.in_house.id,
        )
        self.assertEqual(
            departure_rooms[self.room_occupied.id]["primary_status"], "checkout"
        )
        self.assertEqual(future_departures["kpis"]["in_house"]["value"], 0)
        self.assertEqual(future_departures["kpis"]["reserved"]["value"], 0)
        self.assertEqual(future_departures["kpis"]["occupancy"]["value"], 0.0)
        for key in (
            "arrivals",
            "departures",
            "in_house",
            "reserved",
            "vacant_clean",
            "vacant_dirty",
            "out_of_order",
            "house_use",
        ):
            kpi = future_departures["kpis"][key]
            self.assertEqual(
                self.env[kpi["action"]["res_model"]].search_count(
                    kpi["action"]["domain"]
                ),
                kpi["value"],
                key,
            )

    def test_late_checkout_spans_every_business_day_it_overlaps(self):
        room = self._create_room("W106")
        reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "room_id": room.id,
                "checkin_date": self.start,
                "checkout_date": self.end + timedelta(hours=2),
            }
        )
        bar = self.workspace._planning_bar(
            reservation,
            self.property,
            self.business_date,
            self.business_date + timedelta(days=14),
            False,
        )
        self.assertEqual(bar["span"], 3)
        self.assertEqual(
            bar["end_business_date"],
            fields.Date.to_string(self.business_date + timedelta(days=3)),
        )

    def test_today_marker_uses_property_timezone(self):
        self.property.timezone = "Pacific/Kiritimati"
        start_date = fields.Date.to_date("2026-01-01")
        with patch.object(
            fields.Datetime,
            "now",
            return_value=datetime(2026, 1, 1, 12, 30),
        ):
            days = self.workspace._planning_days(self.property, start_date, 7)
        self.assertFalse(days[0]["is_today"])
        self.assertTrue(days[1]["is_today"])

        self.property.timezone = "Europe/Berlin"
        dst_days = self.workspace._planning_days(
            self.property, fields.Date.to_date("2026-03-28"), 7
        )
        first_end = fields.Datetime.to_datetime(dst_days[0]["end"])
        second_start = fields.Datetime.to_datetime(dst_days[1]["start"])
        self.assertEqual(first_end, second_start)
        self.assertEqual(
            first_end - fields.Datetime.to_datetime(dst_days[0]["start"]),
            timedelta(hours=23),
        )

    def test_attention_is_scoped_to_the_selected_business_day(self):
        stale_date = self.business_date - timedelta(days=10)
        stale_start, stale_end = self.property.get_business_day_bounds(stale_date)
        stale_arrival_room = self._create_room("W107")
        stale_departure_room = self._create_room("W108")
        reservation_model = (
            self.env["hotel.reservation"].sudo().with_context(hotel_migration=True)
        )
        reservation_model.create(
            {
                "partner_id": self.guest.id,
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "room_id": stale_arrival_room.id,
                "checkin_date": stale_start,
                "checkout_date": stale_end,
                "state": "confirmed",
            }
        )
        reservation_model.create(
            {
                "partner_id": self.guest.id,
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "room_id": stale_departure_room.id,
                "checkin_date": stale_start,
                "checkout_date": stale_end,
                "actual_checkin": stale_start,
                "state": "checked_in",
            }
        )

        snapshot = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date
        )
        attention_keys = {item["key"] for item in snapshot["attention"]["items"]}
        self.assertNotIn("late_arrivals", attention_keys)
        self.assertNotIn("overdue_departures", attention_keys)

        future = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date + timedelta(days=7)
        )
        future_keys = {item["key"] for item in future["attention"]["items"]}
        self.assertNotIn("late_arrivals", future_keys)
        self.assertNotIn("overdue_departures", future_keys)

    def test_finance_warnings_include_available_deposits_and_advances(self):
        agency = self.env["res.partner"].create(
            {
                "name": "Workspace Agency",
                "is_hotel_agency": True,
                "hotel_property_ids": [(6, 0, [self.property.id])],
            }
        )
        agency_room = self._create_room("W109")
        agency_reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "agency_id": agency.id,
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "room_id": agency_room.id,
                "checkin_date": self.start,
                "checkout_date": self.end,
            }
        )
        agency_reservation.action_confirm()

        for partner, purpose in (
            (self.guest, "guest_deposit"),
            (agency, "agency_advance"),
        ):
            payment = self.env["account.payment"].create(
                {
                    "amount": 25.0,
                    "date": self.business_date,
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "partner_id": partner.id,
                    "currency_id": self.property.company_id.currency_id.id,
                    "hotel_property_id": self.property.id,
                    "hotel_payment_purpose": purpose,
                }
            )
            payment.action_post()

        finance = self.workspace._finance_by_reservation(
            self.reserved | agency_reservation
        )
        self.assertTrue(finance[self.reserved.id]["has_guest_deposit"])
        self.assertTrue(finance[agency_reservation.id]["has_agency_advance"])

        planning = self.workspace.get_planning_window(
            self.property.id, self.business_date, 7, {}
        )
        bars = {
            bar["id"]: bar
            for floor in planning["floors"]
            for row in floor["rows"]
            for bar in row["reservations"]
        }
        self.assertIn(
            "guest_deposit",
            {warning["key"] for warning in bars[self.reserved.id]["warnings"]},
        )
        self.assertIn(
            "agency_advance",
            {warning["key"] for warning in bars[agency_reservation.id]["warnings"]},
        )

        housekeeper = self.env["res.users"].create(
            {
                "name": "Workspace Housekeeper",
                "login": "workspace_housekeeper_finance",
                "group_ids": [
                    (4, self.env.ref("hotel_base.group_hotel_housekeeping").id)
                ],
                "hotel_property_ids": [(6, 0, [self.property.id])],
                "default_hotel_property_id": self.property.id,
            }
        )
        restricted_workspace = self.workspace.with_user(housekeeper)
        self.assertEqual(
            restricted_workspace._finance_by_reservation(
                self.reserved.with_user(housekeeper)
            ),
            {},
        )
        with self.assertRaises(AccessError):
            restricted_workspace.get_planning_window(
                self.property.id, self.business_date, 7, {}
            )

    def test_open_cashier_session_is_reported_as_non_attention_success(self):
        self.env["hotel.frontdesk.session"].create(
            {
                "property_id": self.property.id,
                "user_id": self.env.user.id,
            }
        )
        snapshot = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date
        )
        cashier_item = next(
            item
            for item in snapshot["attention"]["items"]
            if item["key"] == "cashier_session_open"
        )
        self.assertEqual(cashier_item["severity"], "success")
        self.assertEqual(
            snapshot["attention"]["total"],
            sum(
                item["count"]
                for item in snapshot["attention"]["items"]
                if item["severity"] in ("warning", "danger")
            ),
        )

    def test_property_record_rule_is_enforced(self):
        other_property = self.env["hotel.property"].create(
            {"name": "Workspace Other Hotel", "code": "WSO"}
        )
        frontdesk = self.env["res.users"].create(
            {
                "name": "Workspace Front Desk",
                "login": "workspace_frontdesk",
                "group_ids": [(4, self.env.ref("hotel_base.group_hotel_frontdesk").id)],
                "hotel_property_ids": [(6, 0, [self.property.id])],
                "default_hotel_property_id": self.property.id,
            }
        )
        with self.assertRaises(AccessError):
            self.workspace.with_user(frontdesk).get_workspace_snapshot(
                other_property.id, self.business_date
            )
        with self.assertRaises(AccessError):
            self.workspace.with_user(frontdesk).get_planning_window(
                other_property.id, self.business_date, 14, {}
            )

    def test_reservation_dashboard_compatibility_shim(self):
        legacy = self.env["hotel.reservation"].get_dashboard_data(
            self.property.id, self.business_date
        )
        self.assertEqual(legacy["property_id"], self.property.id)
        self.assertEqual(legacy["reserved"], 1)
        self.assertEqual(legacy["in_house"], 1)
        self.assertEqual(len(legacy["room_board"]), 4)
