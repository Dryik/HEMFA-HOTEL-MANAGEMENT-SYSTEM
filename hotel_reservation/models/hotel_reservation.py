import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)

RESERVATION_STATES = [
    ("draft", "Draft"),
    ("confirmed", "Confirmed"),
    ("checked_in", "Checked In"),
    ("checked_out", "Checked Out"),
    ("cancelled", "Cancelled"),
    ("no_show", "No Show"),
]

# Reservations in these states hold the room against other bookings.
BLOCKING_STATES = ("confirmed", "checked_in")

STATE_COLOR = {
    "draft": 4,        # light blue
    "confirmed": 2,    # orange
    "checked_in": 10,  # green
    "checked_out": 8,  # purple/grey
    "cancelled": 1,    # red
    "no_show": 1,
}


class HotelReservation(models.Model):
    _name = "hotel.reservation"
    _description = "Hotel Reservation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "checkin_date desc, id desc"

    name = fields.Char(
        string="Reservation Number",
        default=lambda self: _("New"),
        copy=False,
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Guest",
        required=True,
        tracking=True,
        context={"default_is_hotel_guest": True, "default_company_type": "person"},
    )
    agency_id = fields.Many2one(
        "res.partner",
        string="Agency / Entity",
        domain=[("is_hotel_agency", "=", True)],
        tracking=True,
        help="Bill-to entity (جهة) this stay is registered under.",
    )
    guest_nationality_id = fields.Many2one(
        related="partner_id.guest_nationality_id", readonly=True
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )
    room_type_id = fields.Many2one("hotel.room.type", tracking=True)
    room_id = fields.Many2one(
        "hotel.room",
        string="Room",
        tracking=True,
        domain="[('property_id', '=', property_id),"
        " ('room_type_id', '=?', room_type_id), ('is_sellable', '=', True)]",
    )
    checkin_date = fields.Datetime(
        string="Arrival",
        required=True,
        tracking=True,
        default=lambda self: self._default_checkin(),
    )
    checkout_date = fields.Datetime(
        string="Departure",
        required=True,
        tracking=True,
        default=lambda self: self._default_checkout(),
    )
    actual_checkin = fields.Datetime(readonly=True, copy=False)
    actual_checkout = fields.Datetime(readonly=True, copy=False)
    nights = fields.Integer(compute="_compute_nights", store=True)
    adults = fields.Integer(default=1)
    children = fields.Integer(default=0)
    state = fields.Selection(
        RESERVATION_STATES,
        default="draft",
        tracking=True,
        copy=False,
        index=True,
    )
    color = fields.Integer(compute="_compute_color")

    # Stay-specific registration fields from the legacy form; identity
    # fields live on the guest partner (hotel_base).
    accommodation_type = fields.Selection(
        [
            ("individual", "Individual"),
            ("family", "Family"),
            ("group", "Group"),
            ("company", "Company / Entity"),
        ],
        default="individual",
    )
    coming_from = fields.Char()
    heading_to = fields.Char()
    trip_number = fields.Char()
    notes = fields.Text()

    # Placeholder pricing until hotel_rate lands: nightly rate seeded
    # from the room type, manually editable by supervisors.
    rate_night = fields.Monetary(
        string="Nightly Rate",
        compute="_compute_rate_night",
        store=True,
        readonly=False,
        tracking=True,
    )
    amount_total = fields.Monetary(compute="_compute_amount_total", store=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    _checkout_after_checkin = models.Constraint(
        "CHECK (checkout_date > checkin_date)",
        "Departure must be after arrival.",
    )

    @api.model
    def _default_checkin(self):
        # Hotel business day starts at noon (12:00 -> 12:00 charging).
        return fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    @api.model
    def _default_checkout(self):
        return self._default_checkin() + timedelta(days=1)

    @api.depends("checkin_date", "checkout_date")
    def _compute_nights(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                rec.nights = max(
                    (rec.checkout_date.date() - rec.checkin_date.date()).days, 1
                )
            else:
                rec.nights = 0

    @api.depends("state")
    def _compute_color(self):
        for rec in self:
            rec.color = STATE_COLOR.get(rec.state, 0)

    @api.depends("room_type_id", "room_id")
    def _compute_rate_night(self):
        for rec in self:
            rtype = rec.room_type_id or rec.room_id.room_type_id
            if rtype and not rec.rate_night:
                rec.rate_night = rtype.base_price

    @api.depends("rate_night", "nights")
    def _compute_amount_total(self):
        for rec in self:
            rec.amount_total = rec.rate_night * rec.nights

    @api.onchange("room_id")
    def _onchange_room_id(self):
        if self.room_id and not self.room_type_id:
            self.room_type_id = self.room_id.room_type_id

    @api.constrains("room_id", "state", "checkin_date", "checkout_date")
    def _check_room_availability(self):
        for rec in self:
            if not rec.room_id or rec.state not in BLOCKING_STATES:
                continue
            if not rec.room_id.is_sellable:
                raise ValidationError(
                    _(
                        "Room %(room)s is out of order or reserved for "
                        "administration.",
                        room=rec.room_id.display_name,
                    )
                )
            overlapping = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("room_id", "=", rec.room_id.id),
                    ("state", "in", BLOCKING_STATES),
                    ("checkin_date", "<", rec.checkout_date),
                    ("checkout_date", ">", rec.checkin_date),
                ]
            )
            if overlapping:
                raise ValidationError(
                    _(
                        "Room %(room)s is already booked between "
                        "%(checkin)s and %(checkout)s.",
                        room=rec.room_id.display_name,
                        checkin=rec.checkin_date,
                        checkout=rec.checkout_date,
                    )
                )

    def init(self):
        # Database-level double-booking guard. Needs btree_gist for
        # integer equality inside a gist exclusion constraint; Python
        # validation above stays as the user-friendly error. On Odoo.sh
        # the db user may not create extensions, so probe first and try
        # the creation silently: without the extension we simply rely
        # on the ORM validation (covered by tests).
        super().init()
        cr = self.env.cr
        cr.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        has_gist = bool(cr.fetchone())
        if not has_gist:
            try:
                with mute_logger("odoo.sql_db"), cr.savepoint():
                    cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
                has_gist = True
            except Exception:
                _logger.info(
                    "btree_gist extension unavailable; room-overlap "
                    "enforcement uses ORM validation only."
                )
        if not has_gist:
            return
        try:
            with cr.savepoint():
                cr.execute(
                    """
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'hotel_reservation_room_no_overlap'
                    """
                )
                if not cr.fetchone():
                    cr.execute(
                        """
                        ALTER TABLE hotel_reservation
                        ADD CONSTRAINT hotel_reservation_room_no_overlap
                        EXCLUDE USING gist (
                            room_id WITH =,
                            tsrange(checkin_date, checkout_date) WITH &&
                        )
                        WHERE (state IN ('confirmed', 'checked_in')
                               AND room_id IS NOT NULL)
                        """
                    )
        except Exception:
            _logger.warning(
                "Could not create the room-overlap exclusion constraint."
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.reservation")
                    or _("New")
                )
            if vals.get("partner_id"):
                partner = self.env["res.partner"].browse(vals["partner_id"])
                if not partner.is_hotel_guest:
                    partner.is_hotel_guest = True
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft reservations can be confirmed."))
            if not rec.room_id:
                raise UserError(_("Assign a room before confirming."))
            rec.state = "confirmed"
            if rec.room_id.occupancy_state == "vacant":
                rec.room_id.occupancy_state = "reserved"

    def action_check_in(self):
        for rec in self:
            if rec.state != "confirmed":
                raise UserError(_("Only confirmed reservations can check in."))
            rec.write(
                {"state": "checked_in", "actual_checkin": fields.Datetime.now()}
            )
            rec.room_id.occupancy_state = "occupied"

    def action_check_out(self):
        for rec in self:
            if rec.state != "checked_in":
                raise UserError(_("Only in-house reservations can check out."))
            rec.write(
                {"state": "checked_out", "actual_checkout": fields.Datetime.now()}
            )
            # Confirmed checkout flips the room dirty so housekeeping
            # picks it up (client requirement: automatic cleaning
            # request on checkout).
            rec.room_id.write(
                {"occupancy_state": "checkout", "hk_status": "dirty"}
            )

    def action_cancel(self):
        for rec in self:
            if rec.state not in ("draft", "confirmed"):
                raise UserError(
                    _("Only draft or confirmed reservations can be cancelled.")
                )
            was_blocking = rec.state in BLOCKING_STATES
            rec.state = "cancelled"
            if was_blocking:
                rec._release_room()

    def action_no_show(self):
        for rec in self:
            if rec.state != "confirmed":
                raise UserError(_("Only confirmed reservations can be no-show."))
            rec.state = "no_show"
            rec._release_room()

    def action_reset_draft(self):
        for rec in self:
            if rec.state not in ("cancelled", "no_show"):
                raise UserError(
                    _("Only cancelled or no-show reservations can be reset.")
                )
            rec.state = "draft"

    def _release_room(self):
        for rec in self.filtered("room_id"):
            other_active = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("room_id", "=", rec.room_id.id),
                    ("state", "in", BLOCKING_STATES),
                    ("checkin_date", "<=", fields.Datetime.now()),
                    ("checkout_date", ">", fields.Datetime.now()),
                ]
            )
            if not other_active and rec.room_id.occupancy_state == "reserved":
                rec.room_id.occupancy_state = "vacant"

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft", "cancelled"):
                raise UserError(_("You can only delete draft or cancelled reservations."))
        return super().unlink()

    @api.model
    def get_dashboard_data(self):
        """KPI payload for the front-desk dashboard (hotel_board)."""
        today_start = fields.Datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_end = today_start + timedelta(days=1)
        rooms = self.env["hotel.room"].search([("active", "=", True)])
        sellable = rooms.filtered("is_sellable")
        occupied = rooms.filtered(lambda r: r.occupancy_state == "occupied")
        arrivals = self.search_count(
            [
                ("state", "=", "confirmed"),
                ("checkin_date", ">=", today_start),
                ("checkin_date", "<", today_end),
            ]
        )
        departures = self.search_count(
            [
                ("state", "=", "checked_in"),
                ("checkout_date", ">=", today_start),
                ("checkout_date", "<", today_end),
            ]
        )
        return {
            "total_rooms": len(rooms),
            "sellable_rooms": len(sellable),
            "occupied": len(occupied),
            "reserved": len(
                rooms.filtered(lambda r: r.occupancy_state == "reserved")
            ),
            "vacant_clean": len(
                rooms.filtered(
                    lambda r: r.occupancy_state == "vacant"
                    and r.hk_status != "dirty"
                    and r.is_sellable
                )
            ),
            "vacant_dirty": len(
                rooms.filtered(
                    lambda r: r.occupancy_state in ("vacant", "checkout")
                    and r.hk_status == "dirty"
                )
            ),
            "out_of_order": len(rooms.filtered("out_of_order")),
            "admin_use": len(rooms.filtered("admin_use")),
            "arrivals_today": arrivals,
            "departures_today": departures,
            "in_house": self.search_count([("state", "=", "checked_in")]),
            "occupancy_pct": round(100 * len(occupied) / len(sellable), 1)
            if sellable
            else 0.0,
        }
