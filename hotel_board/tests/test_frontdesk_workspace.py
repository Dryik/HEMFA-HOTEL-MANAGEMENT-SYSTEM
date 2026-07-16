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
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.property.write(
            {"day_start_hour": 12.0, "timezone": "Africa/Tripoli"}
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
        self.assertEqual(snapshot["meta"]["metric_mode"], "live")
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

    def test_metrics_are_live_for_every_selected_date(self):
        prior_date = self.business_date - timedelta(days=1)
        prior = self.workspace.get_workspace_snapshot(self.property.id, prior_date)
        self.assertEqual(prior["meta"]["metric_mode"], "live")
        self.assertTrue(prior["kpis"]["occupancy"]["available"])

        current = self.workspace.get_workspace_snapshot(
            self.property.id, self.business_date
        )
        self.assertEqual(current["meta"]["metric_mode"], "live")
        self.assertTrue(current["kpis"]["adr"]["available"])
        self.assertEqual(current["kpis"]["occupancy"]["value"], 50.0)
        self.assertEqual(current["kpis"]["adr"]["value"], 150.0)
        self.assertEqual(current["kpis"]["revpar"]["value"], 75.0)

    def test_compact_dashboard_snapshot_and_activity_contract(self):
        snapshot = self.workspace.get_dashboard_snapshot(
            self.property.id, self.business_date
        )
        self.assertEqual(snapshot["version"], 3)
        self.assertEqual(snapshot["meta"]["property_id"], self.property.id)
        self.assertEqual(snapshot["occupancy"]["available_units"], 2)
        self.assertEqual(snapshot["occupancy"]["booked_units"], 2)
        self.assertEqual(snapshot["occupancy"]["percentage"], 50.0)
        tabs = {tab["key"]: tab for tab in snapshot["tabs"]}
        self.assertEqual(
            set(tabs),
            {
                "arrivals",
                "departures",
                "in_house",
                "stayovers",
                "bookings",
                "cancellations",
                "overbookings",
            },
        )
        self.assertEqual(tabs["arrivals"]["count"], 2)
        self.assertEqual(tabs["arrivals"]["pending_count"], 1)
        self.assertEqual(tabs["in_house"]["count"], 1)
        for key, tab in tabs.items():
            all_activity = self.workspace.get_dashboard_activity(
                self.property.id, self.business_date, key, True, False, 50
            )
            pending_activity = self.workspace.get_dashboard_activity(
                self.property.id, self.business_date, key, False, False, 50
            )
            self.assertEqual(tab["count"], all_activity["total"], key)
            self.assertEqual(tab["pending_count"], pending_activity["total"], key)
        self.assertEqual(snapshot["activity"]["key"], "arrivals")
        self.assertEqual(snapshot["activity"]["total"], 1)
        self.assertEqual(
            snapshot["activity"]["rows"][0]["primary_action"]["key"],
            "check_in",
        )
        self.assertNotIn("rooms", snapshot)
        operational_keys = {
            item["key"] for item in snapshot["operational_kpis"]
        }
        self.assertEqual(
            operational_keys,
            {
                "booking_requests",
                "reservations_to_confirm",
                "meals_to_prepare",
                "housekeeping_workload",
            },
        )

        completed = self.workspace.get_dashboard_activity(
            self.property.id,
            self.business_date,
            "arrivals",
            True,
            "Workspace Guest",
            50,
        )
        self.assertEqual(completed["total"], 2)
        self.assertEqual(
            self.env[completed["list_action"]["res_model"]].search_count(
                completed["list_action"]["domain"]
            ),
            completed["total"],
        )
        by_room = self.workspace.get_dashboard_activity(
            self.property.id,
            self.business_date,
            "arrivals",
            True,
            self.room_reserved.name,
            50,
        )
        self.assertEqual([row["id"] for row in by_room["rows"]], [self.reserved.id])

    def test_dashboard_booking_and_cancellation_business_boundaries(self):
        cancelled = self._create_reservation(self.room_empty)
        cancelled.action_cancel()
        booking = self._create_reservation(self.room_empty)
        outside_cancelled = self._create_reservation(self.room_empty)
        outside_cancelled.action_cancel()
        outside_booking = self._create_reservation(self.room_empty)
        business_start, business_end = self.property.get_business_day_bounds(
            self.business_date
        )
        (cancelled | outside_cancelled).flush_recordset(["cancelled_at"])
        (booking | outside_booking).flush_recordset(["create_date"])
        self.env.cr.execute(
            "UPDATE hotel_reservation SET cancelled_at = %s WHERE id = %s",
            [business_start + timedelta(hours=1), cancelled.id],
        )
        self.env.cr.execute(
            "UPDATE hotel_reservation SET create_date = %s WHERE id = %s",
            [business_start + timedelta(hours=2), booking.id],
        )
        self.env.cr.execute(
            "UPDATE hotel_reservation SET cancelled_at = %s WHERE id = %s",
            [business_end, outside_cancelled.id],
        )
        self.env.cr.execute(
            "UPDATE hotel_reservation SET create_date = %s WHERE id = %s",
            [business_end, outside_booking.id],
        )
        (cancelled | outside_cancelled).invalidate_recordset(
            ["cancelled_at"], flush=False
        )
        (booking | outside_booking).invalidate_recordset(
            ["create_date"], flush=False
        )

        cancellations = self.workspace.get_dashboard_activity(
            self.property.id, self.business_date, "cancellations", False, False, 50
        )
        bookings = self.workspace.get_dashboard_activity(
            self.property.id, self.business_date, "bookings", False, False, 50
        )
        self.assertIn(cancelled.id, [row["id"] for row in cancellations["rows"]])
        self.assertIn(booking.id, [row["id"] for row in bookings["rows"]])
        self.assertNotIn(
            outside_cancelled.id, [row["id"] for row in cancellations["rows"]]
        )
        self.assertNotIn(
            outside_booking.id, [row["id"] for row in bookings["rows"]]
        )

    def test_dashboard_activity_searches_reference_inventory_and_sales_parties(self):
        agency = self.env["res.partner"].create(
            {"name": "Searchable Agency", "is_hotel_agency": True}
        )
        group = self.env["hotel.reservation.group"].create(
            {
                "property_id": self.property.id,
                "group_partner_id": self.guest.id,
                "billing_partner_id": self.guest.id,
                "checkin_date": self.start,
                "checkout_date": self.end,
            }
        )
        room = self._create_room("WSEARCH")
        reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "agency_id": agency.id,
                "group_id": group.id,
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "room_id": room.id,
                "checkin_date": self.start,
                "checkout_date": self.end,
            }
        )
        reservation.action_confirm()

        for query in (
            reservation.name,
            room.name,
            self.room_type.name,
            agency.name,
            group.name,
        ):
            activity = self.workspace.get_dashboard_activity(
                self.property.id,
                self.business_date,
                "arrivals",
                False,
                query,
                50,
            )
            self.assertIn(reservation.id, [row["id"] for row in activity["rows"]])

    def test_dashboard_overbooking_prioritizes_blocked_inventory(self):
        self.room_reserved._set_maintenance_block(True)
        self.room_empty._set_maintenance_block(True)
        self.room_dirty._set_maintenance_block(True)
        overbookings = self.workspace.get_dashboard_activity(
            self.property.id, self.business_date, "overbookings", False, False, 50
        )
        self.assertEqual(overbookings["total"], 1)
        self.assertEqual(overbookings["rows"][0]["id"], self.reserved.id)

    def test_dashboard_handles_zero_sellable_inventory(self):
        for room in self.property.room_ids:
            room._set_maintenance_block(True)
        snapshot = self.workspace.get_dashboard_snapshot(
            self.property.id, self.business_date
        )
        self.assertEqual(snapshot["occupancy"]["percentage"], 0.0)
        self.assertEqual(snapshot["occupancy"]["available_units"], 0)
        self.assertEqual(snapshot["occupancy"]["booked_units"], 0)

    def test_dashboard_activity_limits_embedded_rows_without_losing_full_domain(self):
        guest = self.env["res.partner"].create(
            {"name": "Dashboard Truncation Guest", "is_hotel_guest": True}
        )
        reservations = self.env["hotel.reservation"].create(
            [
                {
                    "partner_id": guest.id,
                    "property_id": self.property.id,
                    "room_type_id": self.room_type.id,
                    "checkin_date": self.start,
                    "checkout_date": self.end,
                }
                for _index in range(51)
            ]
        )
        business_start, _business_end = self.property.get_business_day_bounds(
            self.business_date
        )
        for reservation in reservations:
            self.env.cr.execute(
                "UPDATE hotel_reservation SET create_date = %s WHERE id = %s",
                [business_start + timedelta(hours=1), reservation.id],
            )
        reservations.invalidate_recordset(["create_date"])

        activity = self.workspace.get_dashboard_activity(
            self.property.id,
            self.business_date,
            "bookings",
            False,
            guest.name,
            50,
        )
        self.assertEqual(activity["total"], 51)
        self.assertEqual(len(activity["rows"]), 50)
        self.assertTrue(activity["truncated"])
        self.assertEqual(
            self.env[activity["list_action"]["res_model"]].search_count(
                activity["list_action"]["domain"]
            ),
            51,
        )

    def test_dashboard_rejects_unknown_activity_and_excessive_limit(self):
        with self.assertRaises(ValidationError):
            self.workspace.get_dashboard_activity(
                self.property.id, self.business_date, "unknown", False, False, 50
            )
        with self.assertRaises(ValidationError):
            self.workspace.get_dashboard_activity(
                self.property.id, self.business_date, "arrivals", False, False, 51
            )

    def test_planning_includes_empty_rooms_and_actionable_cells(self):
        planning = self.workspace.get_planning_window(
            self.property.id, self.business_date, 14, {}
        )
        self.assertEqual(planning["version"], 2)
        self.assertEqual(planning["meta"]["day_count"], 14)
        self.assertEqual(planning["totals"]["rooms"], 4)
        self.assertEqual(len(planning["days"]), 14)
        rows = {row["id"]: row for floor in planning["floors"] for row in floor["rows"]}
        self.assertIn(self.room_empty.id, rows)
        empty_first_day = rows[self.room_empty.id]["day_statuses"][0]
        self.assertEqual(empty_first_day["primary_status"], "vacant")
        self.assertTrue(empty_first_day["can_create"])
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
        self.assertFalse(
            alerted_rows[self.room_empty.id]["day_statuses"][0]["can_create"]
        )
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
        historical_activity = self.workspace.get_dashboard_activity(
            self.property.id, historical_date, "in_house", False, False, 50
        )
        self.assertIn(historical.id, [row["id"] for row in historical_activity["rows"]])
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
        compact_departures = self.workspace.get_dashboard_activity(
            self.property.id,
            self.business_date + timedelta(days=2),
            "departures",
            False,
            False,
            50,
        )
        self.assertEqual(compact_departures["total"], 2)
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
        stale_arrival = reservation_model.create(
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
        stale_departure = reservation_model.create(
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

        # Freeze the snapshot after today's arrival cutoff. The class fixture
        # contains a legitimate late arrival for the selected day, so this
        # test must assert that the historical records are excluded instead
        # of assuming that the whole queue is empty.
        now = self.start + timedelta(hours=1)
        with patch.object(fields.Datetime, "now", return_value=now):
            snapshot = self.workspace.get_workspace_snapshot(
                self.property.id, self.business_date
            )
            future = self.workspace.get_workspace_snapshot(
                self.property.id, self.business_date + timedelta(days=7)
            )

        attention = {
            item["key"]: item for item in snapshot["attention"]["items"]
        }
        late_action = attention["late_arrivals"]["action"]
        late_ids = set(
            self.env[late_action["res_model"]].search(late_action["domain"]).ids
        )
        self.assertIn(self.reserved.id, late_ids)
        self.assertNotIn(stale_arrival.id, late_ids)

        overdue_action = attention.get("overdue_departures", {}).get("action")
        overdue_ids = (
            set(
                self.env[overdue_action["res_model"]]
                .search(overdue_action["domain"])
                .ids
            )
            if overdue_action
            else set()
        )
        self.assertNotIn(stale_departure.id, overdue_ids)

        future_keys = {item["key"] for item in future["attention"]["items"]}
        self.assertNotIn("late_arrivals", future_keys)
        self.assertNotIn("overdue_departures", future_keys)

    def test_finance_warnings_include_available_deposits_and_advances(self):
        agency = self.env["res.partner"].create(
            {
                "name": "Workspace Agency",
                "is_hotel_agency": True,
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

    def test_active_company_is_authoritative(self):
        other_company = self.env["res.company"].create(
            {"name": "Workspace Other Hotel"}
        )
        other_property = self.env["hotel.property"].with_company(
            other_company
        )._get_default_property()
        self.assertEqual(
            other_property.company_id,
            other_company,
        )
        frontdesk = self.env["res.users"].create(
            {
                "name": "Workspace Front Desk",
                "login": "workspace_frontdesk",
                "group_ids": [(4, self.env.ref("hotel_base.group_hotel_frontdesk").id)],
            }
        )
        snapshot = self.workspace.with_user(frontdesk).get_workspace_snapshot(
            other_property.id, self.business_date
        )
        compact = self.workspace.with_user(frontdesk).get_dashboard_snapshot(
            other_property.id, self.business_date
        )
        planning = self.workspace.with_user(frontdesk).get_planning_window(
            other_property.id, self.business_date, 14, {}
        )
        self.assertEqual(snapshot["meta"]["property_id"], self.property.id)
        self.assertEqual(compact["meta"]["property_id"], self.property.id)
        self.assertEqual(planning["meta"]["property_id"], self.property.id)

    def test_reservation_dashboard_compatibility_shim(self):
        legacy = self.env["hotel.reservation"].get_dashboard_data(
            self.property.id, self.business_date
        )
        self.assertEqual(legacy["property_id"], self.property.id)
        self.assertEqual(legacy["reserved"], 1)
        self.assertEqual(legacy["in_house"], 1)
        self.assertEqual(len(legacy["room_board"]), 4)
