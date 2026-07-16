from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class HotelOwnerDashboard(models.AbstractModel):
    _name = "hotel.owner.dashboard"
    _description = "Hotel Owner Analytics Service"

    @api.model
    def get_dashboard(self, property_id=None, date_from=None, date_to=None):
        if not self.env.user.has_group("hotel_base.group_hotel_manager"):
            raise AccessError(_("Only hotel managers can open the owner dashboard."))
        prop = (
            self.env["hotel.property"].browse(property_id).exists()
            if property_id
            else self.env["hotel.property"]._get_default_property()
        )
        if not prop or prop.company_id not in self.env.companies:
            raise AccessError(_("The hotel is not available in the active companies."))
        today = prop.get_business_date()
        date_to = fields.Date.to_date(date_to or today)
        date_from = fields.Date.to_date(date_from or date_to.replace(day=1))
        if date_to < date_from:
            raise ValidationError(_("The reporting end date must follow the start date."))
        start, _unused = prop.get_business_day_bounds(date_from)
        _unused, end = prop.get_business_day_bounds(date_to)
        day_count = (date_to - date_from).days + 1
        previous_to = date_from - timedelta(days=1)
        previous_from = previous_to - timedelta(days=day_count - 1)
        previous_start, _unused = prop.get_business_day_bounds(previous_from)
        _unused, previous_end = prop.get_business_day_bounds(previous_to)

        reservation_domain = [
            ("property_id", "=", prop.id),
            ("checkin_date", "<", end),
            ("checkout_date", ">=", start),
        ]
        reservations = self.env["hotel.reservation"].search(reservation_domain)
        active = reservations.filtered(
            lambda reservation: reservation.state not in ("cancelled", "no_show")
        )
        cancellations = reservations.filtered(lambda reservation: reservation.state == "cancelled")
        folio_lines = self.env["hotel.folio.line"].search(
            [
                ("folio_id.property_id", "=", prop.id),
                ("service_date", ">=", date_from),
                ("service_date", "<=", date_to),
            ]
        )
        currency = prop.company_id.currency_id

        def converted_revenue(lines):
            total = 0.0
            for line in lines:
                total += line.currency_id._convert(
                    line.amount_total,
                    currency,
                    prop.company_id,
                    line.service_date,
                )
            return currency.round(total)

        revenue = converted_revenue(folio_lines)
        sellable_rooms = self.env["hotel.room"].search_count(
            [("property_id", "=", prop.id), ("is_sellable", "=", True)]
        )
        sold_nights = 0
        for reservation in active:
            arrival = max(reservation.checkin_business_date, date_from)
            departure = min(reservation.checkout_business_date, date_to + timedelta(days=1))
            sold_nights += max((departure - arrival).days, 0)
        available_nights = sellable_rooms * day_count
        occupancy = 100.0 * sold_nights / available_nights if available_nights else 0.0

        previous_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("checkin_date", "<", previous_end),
                ("checkout_date", ">=", previous_start),
                ("state", "not in", ("cancelled", "no_show")),
            ]
        )
        previous_lines = self.env["hotel.folio.line"].search(
            [
                ("folio_id.property_id", "=", prop.id),
                ("service_date", ">=", previous_from),
                ("service_date", "<=", previous_to),
            ]
        )
        previous_revenue = converted_revenue(previous_lines)

        revenue_by_date = defaultdict(float)
        for line in folio_lines:
            revenue_by_date[line.service_date] += line.currency_id._convert(
                line.amount_total, currency, prop.company_id, line.service_date
            )
        bookings_by_date = defaultdict(int)
        source_split = defaultdict(int)
        room_type_data = defaultdict(lambda: {"bookings": 0, "revenue": 0.0})
        geography = defaultdict(int)
        customer_data = defaultdict(lambda: {"bookings": 0, "revenue": 0.0})
        for reservation in active:
            bookings_by_date[reservation.checkin_business_date] += 1
            source_split[reservation.booking_source or "other"] += 1
            room_type_data[reservation.room_type_id.display_name]["bookings"] += 1
            geography[
                reservation.partner_id.guest_nationality_id.name or _("Unknown")
            ] += 1
            customer_data[reservation.partner_id.display_name]["bookings"] += 1
        for line in folio_lines:
            amount = line.currency_id._convert(
                line.amount_total, currency, prop.company_id, line.service_date
            )
            room_type_data[line.folio_id.reservation_id.room_type_id.display_name][
                "revenue"
            ] += amount
            customer_data[line.folio_id.partner_id.display_name]["revenue"] += amount

        trends = []
        cursor = date_from
        while cursor <= date_to:
            trends.append(
                {
                    "date": fields.Date.to_string(cursor),
                    "revenue": currency.round(revenue_by_date[cursor]),
                    "bookings": bookings_by_date[cursor],
                }
            )
            cursor += timedelta(days=1)

        def ranked(mapping, limit=10):
            return sorted(
                [{"label": label, **values} for label, values in mapping.items()],
                key=lambda item: (item.get("revenue", 0), item.get("bookings", 0)),
                reverse=True,
            )[:limit]

        source_labels = dict(self.env["hotel.reservation"]._fields["booking_source"].selection)
        available_properties = self.env["hotel.property"].search(
            [("company_id", "in", self.env.companies.ids), ("active", "=", True)],
            order="company_id, id",
        )
        return {
            "meta": {
                "property_id": prop.id,
                "property_name": prop.company_id.display_name,
                "date_from": fields.Date.to_string(date_from),
                "date_to": fields.Date.to_string(date_to),
                "currency": {
                    "name": currency.name,
                    "symbol": currency.symbol,
                    "position": currency.position,
                    "decimal_places": currency.decimal_places,
                },
                "properties": [
                    {"id": item.id, "name": item.company_id.display_name}
                    for item in available_properties
                ],
            },
            "kpis": {
                "bookings": len(active),
                "revenue": revenue,
                "cancellations": len(cancellations),
                "occupancy": occupancy,
                "pending_arrivals": len(
                    active.filtered(lambda item: item.state == "confirmed" and item.checkin_date <= end)
                ),
                "pending_departures": len(
                    active.filtered(lambda item: item.state == "checked_in" and item.checkout_date <= end)
                ),
            },
            "comparison": {
                "bookings": len(active) - len(previous_reservations),
                "revenue": revenue - previous_revenue,
            },
            "trends": trends,
            "source_split": [
                {"label": source_labels.get(key, key), "bookings": count}
                for key, count in sorted(source_split.items(), key=lambda item: item[1], reverse=True)
            ],
            "room_types": ranked(room_type_data),
            "geography": [
                {"label": label, "bookings": count}
                for label, count in sorted(geography.items(), key=lambda item: item[1], reverse=True)[:10]
            ],
            "top_customers": ranked(customer_data),
        }
