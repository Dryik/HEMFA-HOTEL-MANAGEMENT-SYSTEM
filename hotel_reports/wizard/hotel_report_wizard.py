from datetime import datetime, time, timedelta

from odoo import fields, models

REPORT_TYPES = [
    ("arrivals", "Arrivals"),
    ("departures", "Departures"),
    ("inhouse", "In-House Guests"),
    ("security", "Security / Police List"),
]


class HotelReportWizard(models.TransientModel):
    """Date-driven front-desk report selector.

    One wizard covers the daily movement reports of the legacy system:
    arrivals, departures, in-house and the security (police) list with
    guest identity documents.
    """

    _name = "hotel.report.wizard"
    _description = "Hotel Daily Report Wizard"

    report_type = fields.Selection(
        REPORT_TYPES, required=True, default="arrivals"
    )
    date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        help="Business date the report covers.",
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )

    def _day_window(self):
        self.ensure_one()
        start = datetime.combine(self.date, time.min)
        return start, start + timedelta(days=1)

    def _get_reservations(self):
        """Reservations shown on the selected report."""
        self.ensure_one()
        day_start, day_end = self._day_window()
        base = [("property_id", "=", self.property_id.id)]
        if self.report_type == "arrivals":
            domain = base + [
                ("state", "in", ("confirmed", "checked_in")),
                ("checkin_date", ">=", day_start),
                ("checkin_date", "<", day_end),
            ]
            order = "checkin_date, room_id"
        elif self.report_type == "departures":
            domain = base + [
                ("state", "in", ("checked_in", "checked_out")),
                ("checkout_date", ">=", day_start),
                ("checkout_date", "<", day_end),
            ]
            order = "checkout_date, room_id"
        else:  # inhouse and security share the population
            domain = base + [("state", "=", "checked_in")]
            order = "room_id"
        return self.env["hotel.reservation"].search(domain, order=order)

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            "hotel_reports.action_report_daily_movement"
        ).report_action(self)
