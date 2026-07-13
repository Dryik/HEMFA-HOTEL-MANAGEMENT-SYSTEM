from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


PRIMARY_STATUSES = (
    ("vacant", "Vacant"),
    ("reserved", "Reserved"),
    ("occupied", "Occupied"),
    ("checkout", "Checked Out"),
)
HOUSEKEEPING_STATUSES = (
    ("clean", "Clean"),
    ("dirty", "Dirty"),
    ("inspected", "Inspected"),
)
CAPACITY_BLOCKERS = (
    ("out_of_order", "Out of Order"),
    ("house_use", "House Use"),
)
ALERT_TYPES = (
    ("arrival", "Arrival"),
    ("departure", "Departure"),
    ("dnd", "Do Not Disturb"),
    ("wakeup", "Wake-up Call"),
    ("maintenance", "Maintenance"),
    ("balance", "Balance Due"),
)
PLANNING_DAY_COUNTS = (7, 14, 30)
DEFAULT_PLANNING_STATES = ("draft", "confirmed", "checked_in", "checked_out")


class HotelFrontdeskWorkspace(models.AbstractModel):
    _name = "hotel.frontdesk.workspace"
    _description = "Hotel Front Desk Workspace Service"

    # -- Public API ---------------------------------------------------------

    @api.model
    def get_workspace_snapshot(self, property_id=None, business_date=None):
        """Return one coherent, security-filtered Front Desk snapshot.

        Counts and their drill-down domains are built from the same recordsets.
        This prevents a selected property or business date from being lost when
        an operator opens a KPI.
        """
        prop = self._resolve_property(property_id)
        business_date = self._resolve_business_date(prop, business_date)
        business_start, business_end = prop.get_business_day_bounds(business_date)
        generated_at = fields.Datetime.now()
        context = self._action_context(prop, business_date)

        rooms = self.env["hotel.room"].search(
            [("property_id", "=", prop.id), ("active", "=", True)],
            order="floor_id, name, id",
        )
        overlap_domain = fields.Domain.AND(
            [
                [
                    ("property_id", "=", prop.id),
                    ("room_id", "!=", False),
                    ("state", "in", ("confirmed", "checked_in", "checked_out")),
                ],
                fields.Domain.OR(
                    [
                        [
                            ("checkin_date", "<", business_end),
                            ("checkout_date", ">", business_start),
                        ],
                        [
                            ("actual_checkin", "!=", False),
                            ("actual_checkin", "<", business_end),
                            "|",
                            ("actual_checkout", "=", False),
                            ("actual_checkout", ">", business_start),
                        ],
                        [
                            ("checkout_date", ">=", business_start),
                            ("checkout_date", "<", business_end),
                        ],
                        [
                            ("actual_checkout", ">=", business_start),
                            ("actual_checkout", "<", business_end),
                        ],
                    ]
                ),
            ]
        )
        reservation_candidates = self.env["hotel.reservation"].search(
            overlap_domain,
            order="state desc, checkin_date, id",
        )
        reservations = reservation_candidates.filtered(
            lambda reservation: self._reservation_primary_status(
                reservation, business_date, prop
            )
        )
        reservation_by_room = self._preferred_reservations_by_room(reservations)

        arrivals_domain = [
            ("property_id", "=", prop.id),
            ("state", "in", ("confirmed", "checked_in", "checked_out", "no_show")),
            ("checkin_date", ">=", business_start),
            ("checkin_date", "<", business_end),
        ]
        arrivals = self.env["hotel.reservation"].search(arrivals_domain)
        departures_domain = [
            ("property_id", "=", prop.id),
            ("state", "in", ("confirmed", "checked_in", "checked_out")),
            ("checkout_date", ">=", business_start),
            ("checkout_date", "<", business_end),
        ]
        departures = self.env["hotel.reservation"].search(departures_domain)
        in_house = reservations.filtered(
            lambda reservation: (
                self._reservation_primary_status(reservation, business_date, prop)
                == "occupied"
            )
        )
        reserved = reservations.filtered(
            lambda reservation: (
                self._reservation_primary_status(reservation, business_date, prop)
                == "reserved"
            )
        )

        vacant_rooms = rooms.filtered(lambda room: room.id not in reservation_by_room)
        vacant_clean = vacant_rooms.filtered(
            lambda room: room.is_sellable and room.hk_status != "dirty"
        )
        vacant_dirty = vacant_rooms.filtered(
            lambda room: room.is_sellable and room.hk_status == "dirty"
        )
        out_of_order = rooms.filtered("out_of_order")
        house_use = rooms.filtered("admin_use")

        alert_data = self._get_snapshot_alert_data(
            prop, business_date, business_start, business_end, generated_at
        )
        finance_by_reservation = self._finance_by_reservation(reservations)
        floors = self._snapshot_floors(
            rooms,
            reservation_by_room,
            alert_data,
            finance_by_reservation,
            prop,
            business_date,
        )

        metric_data = self._metric_data(
            prop, business_date, rooms, reservations, context
        )

        def room_action(name, records):
            return self._window_action(
                name,
                "hotel.room",
                [("id", "in", records.ids)],
                context=context,
                views=("kanban", "list", "form"),
            )

        kpis = {
            "arrivals": self._kpi(
                "arrivals",
                _("Arrivals"),
                len(arrivals),
                "integer",
                self._window_action(
                    _("Arrivals"),
                    "hotel.reservation",
                    arrivals_domain,
                    context=context,
                ),
            ),
            "departures": self._kpi(
                "departures",
                _("Departures"),
                len(departures),
                "integer",
                self._window_action(
                    _("Departures"),
                    "hotel.reservation",
                    departures_domain,
                    context=context,
                ),
            ),
            "in_house": self._kpi(
                "in_house",
                _("In House"),
                len(in_house),
                "integer",
                self._window_action(
                    _("In House"),
                    "hotel.reservation",
                    [("id", "in", in_house.ids)],
                    context=context,
                ),
            ),
            "reserved": self._kpi(
                "reserved",
                _("Reserved Rooms"),
                len(reserved),
                "integer",
                self._window_action(
                    _("Reserved Rooms"),
                    "hotel.reservation",
                    [("id", "in", reserved.ids)],
                    context=context,
                ),
            ),
            "vacant_clean": self._kpi(
                "vacant_clean",
                _("Vacant Clean"),
                len(vacant_clean),
                "integer",
                room_action(_("Vacant Clean Rooms"), vacant_clean),
            ),
            "vacant_dirty": self._kpi(
                "vacant_dirty",
                _("Vacant Dirty"),
                len(vacant_dirty),
                "integer",
                room_action(_("Vacant Dirty Rooms"), vacant_dirty),
            ),
            "out_of_order": self._kpi(
                "out_of_order",
                _("Out of Order"),
                len(out_of_order),
                "integer",
                room_action(_("Out of Order Rooms"), out_of_order),
            ),
            "house_use": self._kpi(
                "house_use",
                _("House Use"),
                len(house_use),
                "integer",
                room_action(_("House Use Rooms"), house_use),
            ),
            "occupancy": self._kpi(
                "occupancy",
                _("Occupancy"),
                metric_data["occupancy"],
                "percent",
                metric_data["action"],
                available=metric_data["available"],
                mode=metric_data["mode"],
            ),
            "adr": self._kpi(
                "adr",
                _("ADR"),
                metric_data["adr"],
                "currency",
                metric_data["action"],
                available=metric_data["available"],
                mode=metric_data["mode"],
            ),
            "revpar": self._kpi(
                "revpar",
                _("RevPAR"),
                metric_data["revpar"],
                "currency",
                metric_data["action"],
                available=metric_data["available"],
                mode=metric_data["mode"],
            ),
        }

        attention_items = self._attention_items(
            prop,
            business_date,
            business_start,
            business_end,
            generated_at,
            alert_data,
            vacant_dirty,
            context,
        )
        return {
            "version": 1,
            "meta": self._snapshot_meta(
                prop,
                business_date,
                business_start,
                business_end,
                generated_at,
                metric_data,
            ),
            "properties": self._property_options(),
            "permissions": self._permissions(),
            "kpis": kpis,
            "attention": {
                "total": sum(
                    item["count"]
                    for item in attention_items
                    if item["severity"] in ("warning", "danger")
                ),
                "items": attention_items,
            },
            "floors": floors,
            "legend": self._legend(),
            "actions": {
                "new_reservation": self._new_reservation_action(prop, business_date),
                "planning": self._planning_action(prop, business_date),
            },
        }

    @api.model
    def get_planning_window(
        self,
        property_id=None,
        start_date=None,
        day_count=14,
        filters=None,
    ):
        """Return the complete room inventory for a bounded planning window."""
        prop = self._resolve_property(property_id)
        start_date = self._resolve_business_date(prop, start_date)
        try:
            day_count = int(day_count or 14)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                _("Planning day count must be 7, 14 or 30.")
            ) from error
        if day_count not in PLANNING_DAY_COUNTS:
            raise ValidationError(_("Planning day count must be 7, 14 or 30."))
        filters = self._normalize_planning_filters(filters)
        end_date = start_date + timedelta(days=day_count)
        window_start, _unused = prop.get_business_day_bounds(start_date)
        _unused, window_end = prop.get_business_day_bounds(end_date - timedelta(days=1))
        generated_at = fields.Datetime.now()

        rooms = self.env["hotel.room"].search(
            [("property_id", "=", prop.id), ("active", "=", True)],
            order="floor_id, name, id",
        )
        if filters["floor_ids"]:
            rooms = rooms.filtered(
                lambda room: room.floor_id.id in filters["floor_ids"]
            )
        if filters["room_type_ids"]:
            rooms = rooms.filtered(
                lambda room: room.room_type_id.id in filters["room_type_ids"]
            )
        if filters["hk_statuses"]:
            rooms = rooms.filtered(
                lambda room: room.hk_status in filters["hk_statuses"]
            )
        if filters["room_query"]:
            query = filters["room_query"].casefold()
            rooms = rooms.filtered(lambda room: query in (room.name or "").casefold())

        reservation_domain = [
            ("property_id", "=", prop.id),
            ("room_id", "!=", False),
            ("state", "in", filters["reservation_states"]),
            ("checkin_date", "<", window_end),
            ("checkout_date", ">", window_start),
        ]
        if filters["agency_ids"]:
            reservation_domain.append(("agency_id", "in", filters["agency_ids"]))
        if filters["group_ids"]:
            reservation_domain.append(("group_id", "in", filters["group_ids"]))
        if filters["guest_query"]:
            reservation_domain.append(
                ("partner_id.name", "ilike", filters["guest_query"])
            )
        if filters["reference_query"]:
            reservation_domain.append(("name", "ilike", filters["reference_query"]))
        reservations = self.env["hotel.reservation"].search(
            reservation_domain, order="checkin_date, id"
        )
        blocking_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("room_id", "!=", False),
                ("state", "in", ("confirmed", "checked_in")),
                ("checkin_date", "<", window_end),
                ("checkout_date", ">", window_start),
            ],
            order="state desc, checkin_date, id",
        )

        if any(
            filters[key]
            for key in ("agency_ids", "group_ids", "guest_query", "reference_query")
        ):
            matching_room_ids = set(reservations.mapped("room_id").ids)
            rooms = rooms.filtered(lambda room: room.id in matching_room_ids)
        reservations = reservations.filtered(lambda record: record.room_id in rooms)
        blocking_reservations = blocking_reservations.filtered(
            lambda record: record.room_id in rooms
        )

        first_day_reservations = blocking_reservations.filtered(
            lambda reservation: (
                reservation.checkin_date < prop.get_business_day_bounds(start_date)[1]
                and reservation.checkout_date > window_start
            )
        )
        first_by_room = self._preferred_reservations_by_room(first_day_reservations)
        if filters["room_statuses"]:
            requested_statuses = set(filters["room_statuses"])
            rooms = rooms.filtered(
                lambda room: bool(
                    requested_statuses
                    & set(
                        self._room_status_keys(
                            room, first_by_room.get(room.id), start_date, prop
                        )
                    )
                )
            )
            reservations = reservations.filtered(lambda record: record.room_id in rooms)
            blocking_reservations = blocking_reservations.filtered(
                lambda record: record.room_id in rooms
            )

        day_records = self._planning_days(prop, start_date, day_count)
        planning_alerts = self._get_planning_alert_data(
            prop, window_start, window_end, generated_at
        )
        finance_by_reservation = self._finance_by_reservation(reservations)
        reservations_by_room = defaultdict(lambda: self.env["hotel.reservation"])
        for reservation in reservations:
            reservations_by_room[reservation.room_id.id] |= reservation
        blocking_by_room = defaultdict(lambda: self.env["hotel.reservation"])
        for reservation in blocking_reservations:
            blocking_by_room[reservation.room_id.id] |= reservation

        floor_rows = defaultdict(list)
        for room in rooms:
            room_reservations = reservations_by_room[room.id]
            row_alerts = self._room_alerts(
                room, planning_alerts, prop, start_date, planning=True
            )
            floor_rows[room.floor_id.id].append(
                {
                    "id": room.id,
                    "name": room.name,
                    "floor_id": room.floor_id.id,
                    "floor_name": room.floor_id.display_name,
                    "room_type": {
                        "id": room.room_type_id.id,
                        "name": room.room_type_id.display_name,
                    },
                    "occupancy_status": room.occupancy_state,
                    "hk_status": room.hk_status,
                    "capacity_blocker": self._capacity_blocker(room),
                    "alerts": row_alerts,
                    "day_statuses": self._planning_day_statuses(
                        room,
                        blocking_by_room[room.id],
                        day_records,
                        planning_alerts,
                        prop,
                    ),
                    "reservations": [
                        self._planning_bar(
                            reservation,
                            prop,
                            start_date,
                            end_date,
                            finance_by_reservation.get(reservation.id),
                        )
                        for reservation in room_reservations
                    ],
                }
            )

        floor_payload = []
        for floor in rooms.mapped("floor_id").sorted(
            lambda record: (record.sequence, record.name, record.id)
        ):
            floor_payload.append(
                {
                    "id": floor.id,
                    "name": floor.display_name,
                    "sequence": floor.sequence,
                    "rows": floor_rows[floor.id],
                }
            )

        all_window_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("checkin_date", "<", window_end),
                ("checkout_date", ">", window_start),
                ("state", "not in", ("cancelled", "no_show")),
            ]
        )
        options = self._planning_filter_options(prop, all_window_reservations, rooms)
        currency = self._currency_payload(prop.company_id.currency_id)
        return {
            "version": 1,
            "meta": {
                "property_id": prop.id,
                "property_name": prop.display_name,
                "property_code": prop.code or "",
                "business_date": fields.Date.to_string(start_date),
                "current_business_date": fields.Date.to_string(
                    self._current_business_date(prop)
                ),
                "start_date": fields.Date.to_string(start_date),
                "end_date": fields.Date.to_string(end_date),
                "day_count": day_count,
                "timezone": prop.timezone,
                "day_start_hour": prop.day_start_hour,
                "generated_at": fields.Datetime.to_string(generated_at),
                "currency": currency,
            },
            "properties": self._property_options(),
            "permissions": self._permissions(),
            "days": day_records,
            "filters": {"applied": filters, "options": options},
            "legend": self._planning_legend(),
            "floors": floor_payload,
            "totals": {
                "rooms": len(rooms),
                "reservations": len(reservations),
                "unassigned_reservations": len(
                    all_window_reservations.filtered(lambda record: not record.room_id)
                ),
            },
            "actions": {
                "new_reservation": self._new_reservation_action(prop, start_date),
                "reservation_gantt": self._window_action(
                    _("Reservation Gantt — Read-only"),
                    "hotel.reservation",
                    [
                        ("property_id", "=", prop.id),
                        ("checkin_date", "<", window_end),
                        ("checkout_date", ">", window_start),
                    ],
                    context=self._action_context(prop, start_date),
                    views=("gantt",),
                ),
            },
        }

    @api.model
    def get_legacy_dashboard_data(self, property_id=None, business_date=None):
        """One-release compatibility adapter for the former Owl dashboard."""
        snapshot = self.get_workspace_snapshot(property_id, business_date)
        rooms = []
        for floor in snapshot["floors"]:
            for room in floor["rooms"]:
                reservation = room["reservation"] or {}
                status = room["capacity_blocker"] or room["primary_status"]
                if status == "vacant" and room["hk_status"] == "dirty":
                    status = "dirty"
                rooms.append(
                    {
                        "room_id": room["id"],
                        "room_name": room["name"],
                        "floor_name": room["floor_name"],
                        "room_type": room["room_type"]["name"],
                        "status": status,
                        "reservation_id": reservation.get("id", False),
                        "reservation_name": reservation.get("name", False),
                        "guest_name": reservation.get("guest_name", False),
                        "arrival": reservation.get("arrival", False),
                        "departure": reservation.get("departure", False),
                    }
                )
        kpis = snapshot["kpis"]
        return {
            "property_id": snapshot["meta"]["property_id"],
            "property_name": snapshot["meta"]["property_name"],
            "business_date": snapshot["meta"]["business_date"],
            "properties": snapshot["properties"],
            "total_rooms": sum(
                floor["counts"]["total"] for floor in snapshot["floors"]
            ),
            "sellable_rooms": sum(
                floor["counts"]["sellable"] for floor in snapshot["floors"]
            ),
            "occupied": kpis["in_house"]["value"],
            "reserved": kpis["reserved"]["value"],
            "vacant_clean": kpis["vacant_clean"]["value"],
            "vacant_dirty": kpis["vacant_dirty"]["value"],
            "out_of_order": kpis["out_of_order"]["value"],
            "admin_use": kpis["house_use"]["value"],
            "arrivals_today": kpis["arrivals"]["value"],
            "departures_today": kpis["departures"]["value"],
            "in_house": kpis["in_house"]["value"],
            "occupancy_pct": kpis["occupancy"]["value"] or 0.0,
            "room_board": rooms,
        }

    # -- Resolution, formatting and actions -------------------------------

    def _resolve_property(self, property_id):
        if property_id:
            try:
                property_id = int(property_id)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    _("A valid hotel property is required.")
                ) from error
            prop = self.env["hotel.property"].browse(property_id).exists()
        else:
            prop = self.env["hotel.property"]._get_default_property()
        if not prop:
            raise UserError(_("Assign a default hotel property to your user."))
        prop.ensure_one()
        prop.check_access("read")
        if prop.company_id not in self.env.companies:
            raise AccessError(
                _("You cannot access this property in the active company.")
            )
        return prop

    def _resolve_business_date(self, prop, value):
        try:
            result = fields.Date.to_date(
                value or prop.current_business_date or prop.get_business_date()
            )
        except (TypeError, ValueError) as error:
            raise ValidationError(_("A valid business date is required.")) from error
        if not result:
            raise ValidationError(_("A valid business date is required."))
        return result

    def _current_business_date(self, prop):
        return prop.current_business_date or prop.get_business_date()

    def _property_options(self):
        properties = self.env["hotel.property"].search(
            [
                ("active", "=", True),
                ("company_id", "in", self.env.companies.ids),
            ],
            order="name, id",
        )
        return [
            {
                "id": prop.id,
                "name": prop.display_name,
                "code": prop.code or "",
                "current_business_date": fields.Date.to_string(
                    self._current_business_date(prop)
                ),
            }
            for prop in properties
        ]

    def _permissions(self):
        can_view_finance = self.env.su or any(
            self.env.user.has_group(group)
            for group in (
                "hotel_base.group_hotel_frontdesk",
                "hotel_base.group_hotel_accountant",
                "hotel_base.group_hotel_manager",
            )
        )
        return {
            "can_view_finance": can_view_finance,
            "can_view_cashier": self.env.su
            or self.env.user.has_group("hotel_base.group_hotel_cashier"),
        }

    def _currency_payload(self, currency):
        return {
            "id": currency.id,
            "name": currency.name,
            "symbol": currency.symbol or currency.name,
            "position": currency.position,
            "decimal_places": currency.decimal_places,
        }

    def _action_context(self, prop, business_date, default_checkin=None):
        date_string = fields.Date.to_string(business_date)
        if default_checkin is None:
            default_checkin = prop.get_business_day_bounds(business_date)[0]
        return {
            "default_property_id": prop.id,
            "hotel_property_id": prop.id,
            "hotel_business_date": date_string,
            "default_checkin_date": fields.Datetime.to_string(default_checkin),
        }

    def _window_action(
        self, name, res_model, domain, context=None, views=("list", "form")
    ):
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": res_model,
            "views": [[False, view_type] for view_type in views],
            "domain": domain,
            "context": context or {},
            "target": "current",
        }

    def _record_action(self, record, name=None, context=None):
        action = {
            "type": "ir.actions.act_window",
            "name": name or record.display_name,
            "res_model": record._name,
            "views": [[False, "form"]],
            "res_id": record.id,
            "target": "current",
        }
        if context:
            action["context"] = context
        return action

    def _new_reservation_action(
        self, prop, business_date, room=None, checkin=None, checkout=None
    ):
        if checkin is None or checkout is None:
            checkin, checkout = prop.get_business_day_bounds(business_date)
        context = self._action_context(prop, business_date, default_checkin=checkin)
        context.update(
            {
                "default_checkin_date": fields.Datetime.to_string(checkin),
                "default_checkout_date": fields.Datetime.to_string(checkout),
            }
        )
        if room:
            context.update(
                {
                    "default_room_id": room.id,
                    "default_room_type_id": room.room_type_id.id,
                }
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("New Reservation"),
            "res_model": "hotel.reservation",
            "views": [[False, "form"]],
            "context": context,
            "target": "current",
        }

    def _planning_action(self, prop, business_date):
        return {
            "type": "ir.actions.client",
            "name": _("Planning"),
            "tag": "hotel_board.planning",
            "params": {
                "property_id": prop.id,
                "start_date": fields.Date.to_string(business_date),
                "day_count": 14,
            },
            "context": self._action_context(prop, business_date),
            "target": "current",
        }

    def _kpi(
        self,
        key,
        label,
        value,
        value_format,
        action,
        available=True,
        mode="current",
    ):
        return {
            "key": key,
            "label": label,
            "value": value if available else False,
            "format": value_format,
            "available": available,
            "mode": mode,
            "action": action if available else False,
        }

    # -- Snapshot ----------------------------------------------------------

    def _preferred_reservations_by_room(self, reservations):
        result = {}
        state_priority = {"checked_out": 1, "confirmed": 2, "checked_in": 3}
        for reservation in reservations:
            existing = result.get(reservation.room_id.id)
            if not existing or state_priority.get(
                reservation.state, 0
            ) > state_priority.get(existing.state, 0):
                result[reservation.room_id.id] = reservation
        return result

    def _capacity_blocker(self, room):
        if room.out_of_order:
            return "out_of_order"
        if room.admin_use:
            return "house_use"
        return False

    def _primary_status(self, room, reservation=None, business_date=None, prop=None):
        if reservation and prop and business_date:
            status = self._reservation_primary_status(reservation, business_date, prop)
            if status:
                return status
        if (
            room.occupancy_state == "checkout"
            and prop
            and business_date == self._current_business_date(prop)
        ):
            return "checkout"
        return "vacant"

    def _reservation_primary_status(self, reservation, business_date, prop):
        """Return the stay state on a selected property business day.

        Reservation workflow state describes the record *now*. Historical
        snapshots instead use immutable actual check-in/out timestamps, while
        future snapshots retain the planned confirmed/in-house stay.
        """
        business_start, business_end = prop.get_business_day_bounds(business_date)
        planned_overlap = (
            reservation.checkin_date < business_end
            and reservation.checkout_date > business_start
        )
        planned_departure = business_start <= reservation.checkout_date < business_end
        current_business_date = self._current_business_date(prop)

        if reservation.state == "confirmed":
            if planned_overlap:
                return "reserved"
            return "checkout" if planned_departure else False

        actual_start = reservation.actual_checkin or reservation.checkin_date
        actual_end = reservation.actual_checkout
        if reservation.state == "checked_in":
            if business_date > current_business_date:
                if planned_overlap:
                    return "occupied"
                return "checkout" if planned_departure else False
            if actual_start < business_end and (
                not actual_end or actual_end > business_start
            ):
                return "occupied"
            return (
                "reserved"
                if planned_overlap and actual_start >= business_end
                else False
            )

        if reservation.state == "checked_out":
            actual_end = actual_end or reservation.checkout_date
            actual_departure = business_start <= actual_end < business_end
            if actual_departure:
                return "checkout"
            if actual_start < business_end and actual_end > business_start:
                return "occupied"
            if planned_overlap and actual_start >= business_end:
                return "reserved"
        return False

    def _room_status_keys(self, room, reservation, business_date, prop):
        return tuple(
            key
            for key in (
                self._primary_status(room, reservation, business_date, prop),
                self._capacity_blocker(room),
            )
            if key
        )

    def _label(self, pairs, key):
        label = dict(pairs).get(key)
        return _(label) if label else (key or "")

    def _snapshot_floors(
        self,
        rooms,
        reservation_by_room,
        alert_data,
        finance_by_reservation,
        prop,
        business_date,
    ):
        floor_rooms = defaultdict(list)
        for room in rooms:
            reservation = reservation_by_room.get(room.id)
            primary_status = self._primary_status(
                room, reservation, business_date, prop
            )
            blocker = self._capacity_blocker(room)
            room_alerts = self._room_alerts(room, alert_data, prop, business_date)
            if reservation:
                if reservation.checkin_business_date == business_date:
                    room_alerts.append(
                        self._inline_alert("arrival", _("Arrival"), "info", 1)
                    )
                if reservation.checkout_business_date == business_date:
                    room_alerts.append(
                        self._inline_alert("departure", _("Departure"), "warning", 1)
                    )
                finance = finance_by_reservation.get(reservation.id)
                if finance and finance["has_balance"]:
                    room_alerts.append(
                        self._inline_alert("balance", _("Balance Due"), "warning", 1)
                    )
            reservation_payload = False
            if reservation:
                reservation_payload = {
                    "id": reservation.id,
                    "name": reservation.name,
                    "guest_name": reservation.partner_id.display_name,
                    "arrival": fields.Datetime.to_string(reservation.checkin_date),
                    "departure": fields.Datetime.to_string(reservation.checkout_date),
                    "state": reservation.state,
                }
            aria_parts = [
                _("Room %(room)s", room=room.name),
                self._label(PRIMARY_STATUSES, primary_status),
                self._label(HOUSEKEEPING_STATUSES, room.hk_status),
            ]
            if blocker:
                aria_parts.append(self._label(CAPACITY_BLOCKERS, blocker))
            if reservation:
                aria_parts.append(reservation.partner_id.display_name)
            floor_rooms[room.floor_id.id].append(
                {
                    "id": room.id,
                    "name": room.name,
                    "floor_id": room.floor_id.id,
                    "floor_name": room.floor_id.display_name,
                    "room_type": {
                        "id": room.room_type_id.id,
                        "name": room.room_type_id.display_name,
                    },
                    "primary_status": primary_status,
                    "primary_label": self._label(PRIMARY_STATUSES, primary_status),
                    "occupancy_status": room.occupancy_state,
                    "hk_status": room.hk_status,
                    "hk_label": self._label(HOUSEKEEPING_STATUSES, room.hk_status),
                    "is_sellable": room.is_sellable,
                    "capacity_blocker": blocker,
                    "reservation": reservation_payload,
                    "alerts": room_alerts,
                    "action": self._record_action(
                        reservation or room,
                        _("Reservation") if reservation else _("Room"),
                        context=self._action_context(prop, business_date),
                    ),
                    "aria_label": ", ".join(aria_parts),
                }
            )

        result = []
        for floor in rooms.mapped("floor_id").sorted(
            lambda record: (record.sequence, record.name, record.id)
        ):
            payload_rooms = floor_rooms[floor.id]
            counts = {
                "total": len(payload_rooms),
                "sellable": 0,
                "vacant": 0,
                "reserved": 0,
                "occupied": 0,
                "checkout": 0,
                "out_of_order": 0,
                "house_use": 0,
                "dirty": 0,
            }
            for room in payload_rooms:
                counts[room["primary_status"]] += 1
                if room["is_sellable"]:
                    counts["sellable"] += 1
                if room["capacity_blocker"]:
                    counts[room["capacity_blocker"]] += 1
                if room["hk_status"] == "dirty":
                    counts["dirty"] += 1
            result.append(
                {
                    "id": floor.id,
                    "name": floor.display_name,
                    "sequence": floor.sequence,
                    "collapsed_default": False,
                    "counts": counts,
                    "rooms": payload_rooms,
                }
            )
        return result

    def _metric_data(self, prop, business_date, rooms, reservations, context):
        audit = self.env["hotel.night.audit"].search(
            [
                ("property_id", "=", prop.id),
                ("date", "=", business_date),
                ("state", "=", "done"),
            ],
            order="id desc",
            limit=1,
        )
        if audit:
            action = self._window_action(
                _("Night Audit"),
                "hotel.night.audit",
                [("id", "=", audit.id)],
                context=context,
            )
            return {
                "mode": "actual",
                "label": _("Actual"),
                "available": True,
                "occupancy": round(audit.occupancy_pct, 1),
                "adr": audit.adr,
                "revpar": audit.revpar,
                "action": action,
            }
        if business_date < self._current_business_date(prop):
            return {
                "mode": "unavailable",
                "label": _("Unaudited"),
                "available": False,
                "occupancy": False,
                "adr": False,
                "revpar": False,
                "action": False,
            }

        sellable = rooms.filtered("is_sellable")
        forecast_reservations = reservations.filtered(
            lambda reservation: (
                reservation.room_id in sellable
                and self._reservation_primary_status(reservation, business_date, prop)
                in ("reserved", "occupied")
            )
        )
        occupied_room_ids = set(forecast_reservations.mapped("room_id").ids)
        company_currency = prop.company_id.currency_id
        revenue = 0.0
        for reservation in forecast_reservations:
            revenue += reservation.currency_id._convert(
                reservation.rate_night,
                company_currency,
                prop.company_id,
                business_date,
            )
        occupied_count = len(occupied_room_ids)
        action = self._window_action(
            _("Forecast Stays"),
            "hotel.reservation",
            [("id", "in", forecast_reservations.ids)],
            context=context,
        )
        return {
            "mode": "forecast",
            "label": _("Forecast"),
            "available": True,
            "occupancy": round(100.0 * occupied_count / len(sellable), 1)
            if sellable
            else 0.0,
            "adr": revenue / occupied_count if occupied_count else 0.0,
            "revpar": revenue / len(sellable) if sellable else 0.0,
            "action": action,
        }

    def _snapshot_meta(
        self,
        prop,
        business_date,
        business_start,
        business_end,
        generated_at,
        metric_data,
    ):
        return {
            "property_id": prop.id,
            "property_name": prop.display_name,
            "property_code": prop.code or "",
            "business_date": fields.Date.to_string(business_date),
            "current_business_date": fields.Date.to_string(
                self._current_business_date(prop)
            ),
            "business_start": fields.Datetime.to_string(business_start),
            "business_end": fields.Datetime.to_string(business_end),
            "timezone": prop.timezone,
            "day_start_hour": prop.day_start_hour,
            "generated_at": fields.Datetime.to_string(generated_at),
            "currency": self._currency_payload(prop.company_id.currency_id),
            "metric_mode": metric_data["mode"],
            "metric_label": metric_data["label"],
        }

    def _legend(self):
        return {
            "primary": [
                {"key": key, "label": _(label)} for key, label in PRIMARY_STATUSES
            ]
            + [{"key": key, "label": _(label)} for key, label in CAPACITY_BLOCKERS],
            "housekeeping": [
                {"key": key, "label": _(label)} for key, label in HOUSEKEEPING_STATUSES
            ],
            "alerts": [{"key": key, "label": _(label)} for key, label in ALERT_TYPES],
        }

    # -- Alerts and finance ------------------------------------------------

    def _get_snapshot_alert_data(
        self, prop, business_date, business_start, business_end, now
    ):
        dnd = self.env["hotel.do.not.disturb"].search(
            [("property_id", "=", prop.id), ("state", "=", "active")]
        )
        wakeups = self.env["hotel.wakeup.call"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "scheduled"),
                ("scheduled_at", "<=", now + timedelta(hours=1)),
            ],
            order="scheduled_at, id",
        )
        maintenance = self.env["hotel.maintenance.request"].search(
            [
                ("property_id", "=", prop.id),
                ("room_id", "!=", False),
                ("state", "in", ("new", "confirmed", "in_progress", "done")),
            ]
        )
        return self._alert_maps(dnd, wakeups, maintenance, now)

    def _get_planning_alert_data(self, prop, window_start, window_end, now):
        dnd = self.env["hotel.do.not.disturb"].search(
            [("property_id", "=", prop.id), ("state", "=", "active")]
        )
        wakeups = self.env["hotel.wakeup.call"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "scheduled"),
                ("scheduled_at", ">=", window_start),
                ("scheduled_at", "<", window_end),
            ],
            order="scheduled_at, id",
        )
        maintenance = self.env["hotel.maintenance.request"].search(
            [
                ("property_id", "=", prop.id),
                ("room_id", "!=", False),
                ("state", "in", ("new", "confirmed", "in_progress", "done")),
            ]
        )
        return self._alert_maps(dnd, wakeups, maintenance, now)

    def _alert_maps(self, dnd, wakeups, maintenance, now):
        result = {
            "dnd": dnd,
            "wakeups": wakeups,
            "maintenance": maintenance,
            "dnd_by_room": defaultdict(lambda: self.env["hotel.do.not.disturb"]),
            "wakeups_by_room": defaultdict(lambda: self.env["hotel.wakeup.call"]),
            "maintenance_by_room": defaultdict(
                lambda: self.env["hotel.maintenance.request"]
            ),
            "now": now,
        }
        for record in dnd:
            if record.room_id:
                result["dnd_by_room"][record.room_id.id] |= record
        for record in wakeups:
            if record.room_id:
                result["wakeups_by_room"][record.room_id.id] |= record
        for record in maintenance:
            if record.room_id:
                result["maintenance_by_room"][record.room_id.id] |= record
        return result

    def _inline_alert(self, alert_type, label, severity, count, action=False):
        return {
            "type": alert_type,
            "label": label,
            "severity": severity,
            "count": count,
            "action": action,
        }

    def _room_alerts(self, room, alert_data, prop, business_date, planning=False):
        alerts = []
        dnd = alert_data["dnd_by_room"][room.id]
        if dnd:
            alerts.append(
                self._inline_alert(
                    "dnd",
                    _("Do Not Disturb"),
                    "warning",
                    len(dnd),
                    self._window_action(
                        _("Active Do Not Disturb"),
                        "hotel.do.not.disturb",
                        [("id", "in", dnd.ids)],
                        context=self._action_context(prop, business_date),
                    ),
                )
            )
        wakeups = alert_data["wakeups_by_room"][room.id]
        if wakeups:
            severity = (
                "danger"
                if any(call.scheduled_at < alert_data["now"] for call in wakeups)
                else "warning"
            )
            alerts.append(
                self._inline_alert(
                    "wakeup",
                    _("Wake-up Call"),
                    severity,
                    len(wakeups),
                    self._window_action(
                        _("Wake-up Calls"),
                        "hotel.wakeup.call",
                        [("id", "in", wakeups.ids)],
                        context=self._action_context(prop, business_date),
                    ),
                )
            )
        maintenance = alert_data["maintenance_by_room"][room.id]
        if maintenance:
            severity = "danger" if any(maintenance.mapped("blocks_room")) else "warning"
            alerts.append(
                self._inline_alert(
                    "maintenance",
                    _("Maintenance"),
                    severity,
                    len(maintenance),
                    self._window_action(
                        _("Maintenance"),
                        "hotel.maintenance.request",
                        [("id", "in", maintenance.ids)],
                        context=self._action_context(prop, business_date),
                    ),
                )
            )
        return alerts

    def _finance_by_reservation(self, reservations):
        if not reservations or not self._permissions()["can_view_finance"]:
            return {}
        folios = self.env["hotel.folio"].search(
            [("reservation_id", "in", reservations.ids)]
        )
        totals = defaultdict(
            lambda: {"amount_total": 0.0, "amount_paid": 0.0, "amount_due": 0.0}
        )
        for folio in folios:
            values = totals[folio.reservation_id.id]
            values["amount_total"] += folio.amount_total
            values["amount_paid"] += folio.amount_paid
            values["amount_due"] += folio.amount_due
        partner_ids = set(reservations.mapped("partner_id").ids)
        partner_ids.update(reservations.mapped("agency_id").ids)
        partner_ids.update(reservations.mapped("group_id.billing_partner_id").ids)
        available_by_partner = defaultdict(set)
        if partner_ids:
            # Hotel finance roles explicitly permit these warning flags. Sudo
            # is scoped to the already record-rule-checked property partners;
            # no payment identifiers or accounting lines leave this service.
            payments = (
                self.env["account.payment"]
                .sudo()
                .search(
                    [
                        (
                            "hotel_property_id",
                            "in",
                            reservations.mapped("property_id").ids,
                        ),
                        ("partner_id", "in", list(partner_ids)),
                        (
                            "hotel_payment_purpose",
                            "in",
                            ("guest_deposit", "agency_advance"),
                        ),
                        ("state", "in", ("in_process", "paid")),
                    ]
                )
            )
            for payment in payments:
                if not float_is_zero(
                    payment.hotel_available_advance,
                    precision_rounding=payment.currency_id.rounding,
                ):
                    available_by_partner[payment.partner_id.id].add(
                        payment.hotel_payment_purpose
                    )

        result = {}
        for reservation in reservations:
            values = dict(totals[reservation.id])
            agency_partners = (
                reservation.agency_id | reservation.group_id.billing_partner_id
            )
            values.update(
                {
                    "currency_id": reservation.currency_id.id,
                    "currency_name": reservation.currency_id.name,
                    "has_balance": not float_is_zero(
                        values["amount_due"],
                        precision_rounding=reservation.currency_id.rounding,
                    ),
                    "has_guest_deposit": "guest_deposit"
                    in available_by_partner[reservation.partner_id.id],
                    "has_agency_advance": any(
                        "agency_advance" in available_by_partner[partner.id]
                        for partner in agency_partners
                    ),
                }
            )
            result[reservation.id] = values
        return result

    def _attention_items(
        self,
        prop,
        business_date,
        business_start,
        business_end,
        now,
        alert_data,
        vacant_dirty,
        context,
    ):
        items = []

        def add(key, label, records, severity, model=None):
            count = len(records) if hasattr(records, "ids") else int(records)
            if not count:
                return
            action = False
            if model and hasattr(records, "ids"):
                action = self._window_action(
                    label, model, [("id", "in", records.ids)], context=context
                )
            items.append(
                {
                    "key": key,
                    "label": label,
                    "count": count,
                    "severity": severity,
                    "action": action,
                }
            )

        # Attention is relative to the selected business day. Without the
        # lower window bound, an unresolved record from any historical date
        # would pollute every snapshot; without the cutoff guard, future
        # snapshots would label arrivals and departures as already late.
        attention_cutoff = min(now, business_end)
        if attention_cutoff > business_start:
            late_arrivals = self.env["hotel.reservation"].search(
                [
                    ("property_id", "=", prop.id),
                    ("state", "=", "confirmed"),
                    ("checkin_date", ">=", business_start),
                    ("checkin_date", "<", attention_cutoff),
                ]
            )
            overdue_departures = self.env["hotel.reservation"].search(
                [
                    ("property_id", "=", prop.id),
                    ("state", "=", "checked_in"),
                    ("checkout_date", ">=", business_start),
                    ("checkout_date", "<", attention_cutoff),
                ]
            )
        else:
            late_arrivals = self.env["hotel.reservation"]
            overdue_departures = self.env["hotel.reservation"]
        add(
            "late_arrivals",
            _("Late Arrivals"),
            late_arrivals,
            "danger",
            "hotel.reservation",
        )
        add(
            "overdue_departures",
            _("Overdue Departures"),
            overdue_departures,
            "danger",
            "hotel.reservation",
        )
        add(
            "wakeup_calls",
            _("Wake-up Calls Due"),
            alert_data["wakeups"],
            "danger"
            if any(call.scheduled_at < now for call in alert_data["wakeups"])
            else "warning",
            "hotel.wakeup.call",
        )
        add(
            "active_dnd",
            _("Active Do Not Disturb"),
            alert_data["dnd"],
            "warning",
            "hotel.do.not.disturb",
        )
        blocking_maintenance = alert_data["maintenance"].filtered(
            lambda request: (
                request.blocks_room
                and request.state in ("confirmed", "in_progress", "done")
            )
        )
        add(
            "blocking_maintenance",
            _("Blocking Maintenance"),
            blocking_maintenance,
            "danger",
            "hotel.maintenance.request",
        )
        add(
            "vacant_dirty",
            _("Vacant Dirty Rooms"),
            vacant_dirty,
            "warning",
            "hotel.room",
        )

        audit = self.env["hotel.night.audit"].search(
            [
                ("property_id", "=", prop.id),
                ("date", "=", business_date),
                ("state", "=", "done"),
            ],
            limit=1,
        )
        if business_date <= self._current_business_date(prop) and not audit:
            items.append(
                {
                    "key": "pending_night_audit",
                    "label": _("Pending Night Audit"),
                    "count": 1,
                    "severity": "warning",
                    "action": self._window_action(
                        _("Night Audit"),
                        "hotel.night.audit",
                        [
                            ("property_id", "=", prop.id),
                            ("date", "=", business_date),
                        ],
                        context=context,
                    ),
                }
            )

        permissions = self._permissions()
        if permissions["can_view_cashier"]:
            open_session = self.env["hotel.frontdesk.session"].search(
                [
                    ("property_id", "=", prop.id),
                    ("user_id", "=", self.env.uid),
                    ("state", "=", "opened"),
                ]
            )
            if not open_session:
                items.append(
                    {
                        "key": "cashier_session_missing",
                        "label": _("Open a Cashier Session"),
                        "count": 1,
                        "severity": "warning",
                        "action": self._window_action(
                            _("Cashier Sessions"),
                            "hotel.frontdesk.session",
                            [
                                ("property_id", "=", prop.id),
                                ("user_id", "=", self.env.uid),
                            ],
                            context=context,
                        ),
                    }
                )
            else:
                items.append(
                    {
                        "key": "cashier_session_open",
                        "label": _("Cashier Session Open"),
                        "count": len(open_session),
                        "severity": "success",
                        "action": self._window_action(
                            _("Cashier Sessions"),
                            "hotel.frontdesk.session",
                            [("id", "in", open_session.ids)],
                            context=context,
                        ),
                    }
                )
            variance_sessions = self.env["hotel.frontdesk.session"].search(
                [
                    ("property_id", "=", prop.id),
                    ("state", "=", "closed"),
                    ("date_closed", ">=", business_start),
                    ("date_closed", "<", business_end),
                    ("difference", "!=", 0.0),
                ]
            )
            add(
                "cashier_variance",
                _("Cashier Variances"),
                variance_sessions,
                "danger",
                "hotel.frontdesk.session",
            )

        if permissions["can_view_finance"]:
            due_reservations = self.env["hotel.reservation"].search(
                [
                    ("property_id", "=", prop.id),
                    ("state", "=", "checked_in"),
                    ("checkout_date", "<", business_end),
                ]
            )
            due_folios = self.env["hotel.folio"].search(
                [
                    ("reservation_id", "in", due_reservations.ids),
                    ("amount_due", "!=", 0.0),
                ]
            )
            add(
                "folios_due",
                _("Folios Requiring Settlement"),
                due_folios,
                "danger",
                "hotel.folio",
            )
        return items

    # -- Planning ----------------------------------------------------------

    def _normalize_planning_filters(self, values):
        values = values if isinstance(values, dict) else {}

        def ids(key):
            raw = values.get(key) or []
            if not isinstance(raw, (list, tuple, set)):
                raw = [raw]
            result = []
            for value in raw:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    result.append(value)
            return list(dict.fromkeys(result))

        def strings(key, default=()):
            raw = values.get(key)
            if raw in (None, False, ""):
                raw = default
            if not isinstance(raw, (list, tuple, set)):
                raw = [raw]
            return list(dict.fromkeys(str(value) for value in raw if value))

        def query(key):
            return str(values.get(key) or "").strip()[:100]

        reservation_states = strings("reservation_states", DEFAULT_PLANNING_STATES)
        valid_states = dict(
            self.env["hotel.reservation"]
            ._fields["state"]
            ._description_selection(self.env)
        )
        reservation_states = [
            state for state in reservation_states if state in valid_states
        ] or list(DEFAULT_PLANNING_STATES)
        valid_room_statuses = {
            key for key, _label in PRIMARY_STATUSES + CAPACITY_BLOCKERS
        }
        valid_hk_statuses = {key for key, _label in HOUSEKEEPING_STATUSES}
        return {
            "floor_ids": ids("floor_ids"),
            "room_type_ids": ids("room_type_ids"),
            "room_statuses": [
                value
                for value in strings("room_statuses")
                if value in valid_room_statuses
            ],
            "hk_statuses": [
                value for value in strings("hk_statuses") if value in valid_hk_statuses
            ],
            "reservation_states": reservation_states,
            "agency_ids": ids("agency_ids"),
            "group_ids": ids("group_ids"),
            "guest_query": query("guest_query"),
            "room_query": query("room_query"),
            "reference_query": query("reference_query"),
        }

    def _planning_days(self, prop, start_date, day_count):
        today = fields.Datetime.context_timestamp(
            self.with_context(tz=prop.timezone), fields.Datetime.now()
        ).date()
        result = []
        for index in range(day_count):
            date = start_date + timedelta(days=index)
            start, end = prop.get_business_day_bounds(date)
            result.append(
                {
                    "date": fields.Date.to_string(date),
                    "label": str(date.day),
                    "weekday": date.strftime("%a"),
                    "index": index,
                    "is_today": date == today,
                    "is_business_date": date == self._current_business_date(prop),
                    "start": fields.Datetime.to_string(start),
                    "end": fields.Datetime.to_string(end),
                }
            )
        return result

    def _planning_day_statuses(self, room, reservations, days, alert_data, prop):
        result = []
        for day in days:
            business_date = fields.Date.to_date(day["date"])
            day_start = fields.Datetime.to_datetime(day["start"])
            day_end = fields.Datetime.to_datetime(day["end"])
            active = reservations.filtered(
                lambda reservation: (
                    reservation.state in ("confirmed", "checked_in")
                    and reservation.checkin_date < day_end
                    and reservation.checkout_date > day_start
                )
            )
            reservation = self._preferred_reservations_by_room(active).get(room.id)
            alert_types = []
            if alert_data["dnd_by_room"][
                room.id
            ] and business_date == self._current_business_date(prop):
                alert_types.append("dnd")
            if alert_data["maintenance_by_room"][room.id]:
                alert_types.append("maintenance")
            if any(
                prop.get_business_date(call.scheduled_at) == business_date
                for call in alert_data["wakeups_by_room"][room.id]
            ):
                alert_types.append("wakeup")
            result.append(
                {
                    "date": day["date"],
                    "index": day["index"],
                    "primary_status": self._primary_status(
                        room, reservation, business_date, prop
                    ),
                    "hk_status": room.hk_status,
                    "capacity_blocker": self._capacity_blocker(room),
                    "alert_types": alert_types,
                    "reservation_id": reservation.id if reservation else False,
                    "reservation_action": self._record_action(
                        reservation,
                        _("Reservation"),
                        context=self._action_context(prop, business_date),
                    )
                    if reservation
                    else False,
                    "action": False
                    if reservation or not room.is_sellable
                    else self._new_reservation_action(
                        prop,
                        business_date,
                        room,
                        checkin=day_start,
                        checkout=day_end,
                    ),
                }
            )
        return result

    def _planning_bar(
        self, reservation, prop, window_start_date, window_end_date, finance
    ):
        start_date = prop.get_business_date(reservation.checkin_date)
        end_date = prop.get_business_date(reservation.checkout_date)
        end_boundary = prop.get_business_day_bounds(end_date)[0]
        if reservation.checkout_date > end_boundary:
            end_date += timedelta(days=1)
        clipped_start_date = max(start_date, window_start_date)
        clipped_end_date = min(end_date, window_end_date)
        span = max((clipped_end_date - clipped_start_date).days, 1)
        state_labels = dict(
            reservation._fields["state"]._description_selection(self.env)
        )
        bill_to = (
            reservation.group_id.billing_partner_id
            or reservation.agency_id
            or reservation.partner_id
        )
        warnings = []
        if finance and finance["has_balance"]:
            warnings.append(
                {
                    "key": "balance_due",
                    "label": _("Balance Due"),
                    "severity": "warning",
                }
            )
        if finance and finance["has_guest_deposit"]:
            warnings.append(
                {
                    "key": "guest_deposit",
                    "label": _("Guest Deposit Available"),
                    "severity": "info",
                }
            )
        if finance and finance["has_agency_advance"]:
            warnings.append(
                {
                    "key": "agency_advance",
                    "label": _("Agency Advance Available"),
                    "severity": "info",
                }
            )
        return {
            "id": reservation.id,
            "name": reservation.name,
            "guest": {
                "id": reservation.partner_id.id,
                "name": reservation.partner_id.display_name,
            },
            "state": reservation.state,
            "state_label": state_labels.get(reservation.state, reservation.state),
            "start_datetime": fields.Datetime.to_string(reservation.checkin_date),
            "end_datetime": fields.Datetime.to_string(reservation.checkout_date),
            "start_business_date": fields.Date.to_string(start_date),
            "end_business_date": fields.Date.to_string(end_date),
            "start_index": (clipped_start_date - window_start_date).days,
            "span": span,
            "clipped_start": start_date < window_start_date,
            "clipped_end": end_date > window_end_date,
            "agency": self._many2one_payload(reservation.agency_id),
            "group": self._many2one_payload(reservation.group_id),
            "bill_to": self._many2one_payload(bill_to),
            "finance": finance or False,
            "warnings": warnings,
            "action": self._record_action(
                reservation,
                _("Reservation"),
                context=self._action_context(prop, window_start_date),
            ),
        }

    def _many2one_payload(self, record):
        return {"id": record.id, "name": record.display_name} if record else False

    def _planning_filter_options(self, prop, reservations, rooms):
        state_labels = dict(
            self.env["hotel.reservation"]
            ._fields["state"]
            ._description_selection(self.env)
        )
        floors = self.env["hotel.floor"].search(
            [("property_id", "=", prop.id), ("active", "=", True)],
            order="sequence, name, id",
        )
        room_types = self.env["hotel.room.type"].search(
            [
                ("active", "=", True),
                "|",
                ("property_id", "=", False),
                ("property_id", "=", prop.id),
            ],
            order="name, id",
        )
        return {
            "floors": [self._many2one_payload(record) for record in floors],
            "room_types": [self._many2one_payload(record) for record in room_types],
            "room_statuses": [
                {"key": key, "label": _(label)}
                for key, label in PRIMARY_STATUSES + CAPACITY_BLOCKERS
            ],
            "housekeeping_statuses": [
                {"key": key, "label": _(label)} for key, label in HOUSEKEEPING_STATUSES
            ],
            "reservation_states": [
                {"key": key, "label": label} for key, label in state_labels.items()
            ],
            "agencies": [
                self._many2one_payload(record)
                for record in reservations.mapped("agency_id").sorted("name")
            ],
            "groups": [
                self._many2one_payload(record)
                for record in reservations.mapped("group_id").sorted("name")
            ],
        }

    def _planning_legend(self):
        result = self._legend()
        result["reservation_states"] = [
            {"key": key, "label": label}
            for key, label in self.env["hotel.reservation"]
            ._fields["state"]
            ._description_selection(self.env)
        ]
        return result
