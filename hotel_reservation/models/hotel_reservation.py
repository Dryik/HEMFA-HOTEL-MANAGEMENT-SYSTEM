import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)

RESERVATION_STATES = [
    ("draft", "Draft"),
    ("pending_payment", "Pending Payment"),
    ("confirmed", "Confirmed"),
    ("checked_in", "Checked In"),
    ("checked_out", "Checked Out"),
    ("cancelled", "Cancelled"),
    ("no_show", "No Show"),
]

# Reservations in these states hold the room against other bookings.
BLOCKING_STATES = ("pending_payment", "confirmed", "checked_in")

STATE_COLOR = {
    "draft": 4,        # light blue
    "pending_payment": 3,
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
    group_id = fields.Many2one(
        "hotel.reservation.group", string="Group / Block", index=True, ondelete="set null"
    )
    amendment_ids = fields.One2many(
        "hotel.reservation.amendment", "reservation_id", string="Amendments"
    )
    guest_nationality_id = fields.Many2one(
        related="partner_id.guest_nationality_id", store=True, readonly=True
    )
    guest_country_id = fields.Many2one(
        related="partner_id.country_id", store=True, readonly=True
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    # Exposed so client-side domains (e.g. the pricelist company filter) can
    # reference the property's company directly. A Many2one is only an id in
    # the web domain evaluator, so a dotted path like ``property_id.company_id``
    # cannot be traversed there and yields an invalid domain term.
    company_id = fields.Many2one(
        "res.company",
        related="property_id.company_id",
        store=True,
        index=True,
        readonly=True,
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
    checkin_business_date = fields.Date(
        compute="_compute_business_dates", store=True, index=True
    )
    checkout_business_date = fields.Date(
        compute="_compute_business_dates", store=True, index=True
    )
    actual_checkout_business_date = fields.Date(
        compute="_compute_business_dates", store=True, index=True
    )
    nights = fields.Integer(compute="_compute_nights", store=True)
    adults = fields.Integer(default=1)
    teenagers = fields.Integer(default=0)
    children = fields.Integer(default=0)
    infants = fields.Integer(default=0)
    booking_source = fields.Selection(
        [
            ("direct", "Direct"),
            ("website", "Website"),
            ("agent", "Agent"),
            ("ota_manual", "OTA (Manual)"),
            ("other", "Other"),
        ],
        default="direct",
        required=True,
        tracking=True,
    )
    responsible_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, tracking=True
    )
    pricelist_id = fields.Many2one(
        "product.pricelist",
        string="Pricelist",
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        tracking=True,
    )
    hold_expires_at = fields.Datetime(readonly=True, copy=False, index=True)
    cancelled_at = fields.Datetime(readonly=True, copy=False, index=True)
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
        prop = self.env["hotel.property"]._get_default_property()
        if prop:
            start, _end = prop.get_business_day_bounds(prop.get_business_date())
            return start
        return fields.Datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)

    @api.model
    def _default_checkout(self):
        return self._default_checkin() + timedelta(days=1)

    @api.depends(
        "checkin_date",
        "checkout_date",
        "property_id.day_start_hour",
        "property_id.timezone",
    )
    def _compute_nights(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date:
                if rec.property_id:
                    checkin_date = rec.property_id.get_business_date(rec.checkin_date)
                    checkout_date = rec.property_id.get_business_date(rec.checkout_date)
                else:
                    checkin_date = rec.checkin_date.date()
                    checkout_date = rec.checkout_date.date()
                rec.nights = max(
                    (checkout_date - checkin_date).days, 1
                )
            else:
                rec.nights = 0

    @api.depends(
        "checkin_date",
        "checkout_date",
        "actual_checkout",
        "property_id.day_start_hour",
        "property_id.timezone",
    )
    def _compute_business_dates(self):
        for rec in self:
            prop = rec.property_id
            rec.checkin_business_date = (
                prop.get_business_date(rec.checkin_date)
                if prop and rec.checkin_date
                else False
            )
            rec.checkout_business_date = (
                prop.get_business_date(rec.checkout_date)
                if prop and rec.checkout_date
                else False
            )
            rec.actual_checkout_business_date = (
                prop.get_business_date(rec.actual_checkout)
                if prop and rec.actual_checkout
                else False
            )

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

    @api.constrains(
        "property_id",
        "room_type_id",
        "room_id",
        "adults",
        "teenagers",
        "children",
        "infants",
    )
    def _check_property_and_capacity(self):
        for rec in self:
            if rec.room_type_id.property_id and rec.room_type_id.property_id != rec.property_id:
                raise ValidationError(
                    _("The room type must be shared or belong to the reservation property.")
                )
            if rec.room_id and rec.room_id.property_id != rec.property_id:
                raise ValidationError(_("The room must belong to the reservation property."))
            if rec.room_id and rec.room_type_id and rec.room_id.room_type_id != rec.room_type_id:
                raise ValidationError(_("The selected room does not match the room type."))
            if min(rec.adults, rec.teenagers, rec.children, rec.infants) < 0:
                raise ValidationError(_("Guest counts cannot be negative."))
            room_type = rec.room_type_id or rec.room_id.room_type_id
            if room_type and (
                rec.adults > room_type.capacity_adults
                or rec.teenagers > room_type.capacity_teenagers
                or rec.children > room_type.capacity_children
                or rec.infants > room_type.capacity_infants
            ):
                raise ValidationError(
                    _(
                        "Guest counts exceed the capacity of %(room_type)s.",
                        room_type=room_type.display_name,
                    )
                )

    @api.constrains("room_id", "state", "checkin_date", "checkout_date")
    def _check_room_availability(self):
        for rec in self:
            if not rec.room_id or rec.state not in BLOCKING_STATES:
                continue
            self.env["hotel.availability.service"].assert_room_available(
                rec.room_id,
                rec.checkin_date,
                rec.checkout_date,
                exclude_reservation_id=rec.id,
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
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname = 'hotel_reservation_room_no_overlap'
                    """
                )
                existing = cr.fetchone()
                if existing and "pending_payment" not in existing[0]:
                    cr.execute(
                        "ALTER TABLE hotel_reservation "
                        "DROP CONSTRAINT hotel_reservation_room_no_overlap"
                    )
                    existing = False
                if not existing:
                    cr.execute(
                        """
                        ALTER TABLE hotel_reservation
                        ADD CONSTRAINT hotel_reservation_room_no_overlap
                        EXCLUDE USING gist (
                            room_id WITH =,
                            tsrange(checkin_date, checkout_date) WITH &&
                        )
                        WHERE (state IN ('pending_payment', 'confirmed', 'checked_in')
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
            if not self.env.su and (
                vals.get("state", "draft") != "draft"
                or vals.get("actual_checkin")
                or vals.get("actual_checkout")
                or vals.get("cancelled_at")
                or vals.get("name") not in (None, False, _("New"))
            ):
                raise UserError(
                    _("Reservations must enter confirmed and stay states through workflow actions.")
                )
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.reservation")
                    or _("New")
                )
            property_id = vals.get("property_id")
            if not property_id:
                property_id = self.env["hotel.property"]._get_default_property().id
                vals["property_id"] = property_id
            prop = self.env["hotel.property"].browse(property_id)
            if vals.get("partner_id"):
                partner = self.env["res.partner"].browse(vals["partner_id"])
                partner._assign_hotel_property(prop)
                if not partner.is_hotel_guest:
                    partner.is_hotel_guest = True
            if vals.get("agency_id"):
                self.env["res.partner"].browse(vals["agency_id"])._assign_hotel_property(
                    prop
                )
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if rec.state not in ("draft", "pending_payment"):
                raise UserError(_("Only draft or held reservations can be confirmed."))
            if not rec.room_id:
                raise UserError(_("Assign a room before confirming."))
            self.env["hotel.availability.service"].assert_room_available(
                rec.room_id,
                rec.checkin_date,
                rec.checkout_date,
                exclude_reservation_id=rec.id,
            )
            rec._write_workflow_values(
                {"state": "confirmed", "hold_expires_at": False}
            )

    def _action_hold_for_payment(self, expires_at):
        for rec in self:
            if rec.state != "draft" or not rec.room_id:
                raise UserError(_("Only an allocated draft reservation can be held."))
            self.env["hotel.availability.service"].assert_room_available(
                rec.room_id,
                rec.checkin_date,
                rec.checkout_date,
                exclude_reservation_id=rec.id,
            )
            rec._write_workflow_values(
                {"state": "pending_payment", "hold_expires_at": expires_at}
            )
        return True

    def _action_expire_payment_hold(self):
        held = self.filtered(lambda rec: rec.state == "pending_payment")
        held._write_workflow_values(
            {
                "state": "cancelled",
                "hold_expires_at": False,
                "cancelled_at": fields.Datetime.now(),
            }
        )
        held._release_room()
        return True

    def action_check_in(self):
        for rec in self:
            if rec.state != "confirmed":
                raise UserError(_("Only confirmed reservations can check in."))
            rec._write_workflow_values(
                {"state": "checked_in", "actual_checkin": fields.Datetime.now()}
            )
            rec.room_id._set_stay_occupancy("occupied")

    def action_check_out(self):
        for rec in self:
            if rec.state != "checked_in":
                raise UserError(_("Only in-house reservations can check out."))
            rec._write_workflow_values(
                {"state": "checked_out", "actual_checkout": fields.Datetime.now()}
            )
            # Confirmed checkout flips the room dirty so housekeeping
            # picks it up (client requirement: automatic cleaning
            # request on checkout).
            rec.room_id._set_stay_occupancy("checkout", hk_status="dirty")

    def action_cancel(self):
        for rec in self:
            if rec.state not in ("draft", "pending_payment", "confirmed"):
                raise UserError(
                    _("Only draft, held, or confirmed reservations can be cancelled.")
                )
            was_blocking = rec.state in BLOCKING_STATES
            rec._write_workflow_values(
                {
                    "state": "cancelled",
                    "hold_expires_at": False,
                    "cancelled_at": fields.Datetime.now(),
                }
            )
            if was_blocking:
                rec._release_room()

    def action_no_show(self):
        for rec in self:
            if rec.state != "confirmed":
                raise UserError(_("Only confirmed reservations can be no-show."))
            rec._write_workflow_values({"state": "no_show"})
            rec._release_room()

    def action_reset_draft(self):
        for rec in self:
            if rec.state not in ("cancelled", "no_show"):
                raise UserError(
                    _("Only cancelled or no-show reservations can be reset.")
                )
            rec._write_workflow_values({"state": "draft", "cancelled_at": False})

    def _write_workflow_values(self, values):
        return super(HotelReservation, self).write(values)

    def _write_amendment_values(self, values):
        return super(HotelReservation, self).write(values)

    def _write_quote_values(self, values):
        """Apply a server-recomputed quote to draft or payment-held inventory."""
        if self.filtered(lambda reservation: reservation.state not in ("draft", "pending_payment")):
            raise UserError(_("Only draft or payment-held reservations can be repriced."))
        return super(HotelReservation, self).write(values)

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
                rec.room_id._set_stay_occupancy("vacant")

    def action_open_available_rooms(self):
        self.ensure_one()
        available = self.env["hotel.availability.service"].get_available_rooms(
            self.property_id.id,
            self.checkin_date,
            self.checkout_date,
            self.room_type_id.id,
            exclude_reservation_id=self.id,
        )
        return {
            "name": _("Available Rooms"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.room",
            "view_mode": "list,form",
            "domain": [("id", "in", available.ids)],
            "context": {"create": False},
        }

    def action_request_amendment(self):
        self.ensure_one()
        if self.state not in ("confirmed", "checked_in"):
            raise UserError(
                _("Only confirmed or in-house reservations can be amended.")
            )
        return {
            "name": _("Request Amendment"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.reservation.amendment",
            "views": [
                (
                    self.env.ref(
                        "hotel_reservation.hotel_reservation_amendment_view_form"
                    ).id,
                    "form",
                )
            ],
            "view_mode": "form",
            "target": "current",
            "context": {"default_reservation_id": self.id},
        }

    def write(self, vals):
        migration = self.env.su and self.env.context.get("hotel_migration")
        lifecycle_fields = {
            "name",
            "actual_checkin",
            "actual_checkout",
            "cancelled_at",
        }
        if not migration and lifecycle_fields.intersection(vals):
            raise UserError(
                _(
                    "Reservation identity and lifecycle timestamps are assigned "
                    "by the workflow."
                )
            )
        protected = {
            "partner_id",
            "agency_id",
            "group_id",
            "property_id",
            "room_type_id",
            "room_id",
            "checkin_date",
            "checkout_date",
            "rate_night",
            "adults",
            "teenagers",
            "children",
            "infants",
            "booking_source",
            "responsible_id",
            "pricelist_id",
            "currency_id",
        }
        locked = self.filtered(
            lambda reservation: reservation.state != "draft"
        )
        if not migration and not locked:
            for reservation in self:
                prop = self.env["hotel.property"].browse(
                    vals.get("property_id") or reservation.property_id.id
                )
                partner = self.env["res.partner"].browse(
                    vals.get("partner_id") or reservation.partner_id.id
                )
                partner._assign_hotel_property(prop)
                if not partner.is_hotel_guest:
                    partner.is_hotel_guest = True
                agency = self.env["res.partner"].browse(
                    vals.get("agency_id")
                    if "agency_id" in vals
                    else reservation.agency_id.id
                )
                if agency:
                    agency._assign_hotel_property(prop)
        if (
            "state" in vals
            and not migration
            and any(reservation.state != vals["state"] for reservation in self)
        ):
            raise UserError(
                _("Reservation status can only be changed through its workflow actions.")
            )
        if (
            locked
            and protected.intersection(vals)
            and not migration
        ):
            raise UserError(
                _(
                    "Confirmed and in-house stays must be changed through an "
                    "approved reservation amendment."
                )
            )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state not in ("draft", "cancelled"):
                raise UserError(_("You can only delete draft or cancelled reservations."))
        return super().unlink()

    @api.model
    def get_dashboard_data(self, property_id=None, business_date=None):
        """KPI payload for the front-desk dashboard (hotel_board)."""
        # One-release compatibility shim.  ``hotel_reservation`` remains
        # independently installable, so keep the former implementation below
        # as a fallback when ``hotel_board`` is not installed yet.
        if "hotel.frontdesk.workspace" in self.env:
            return self.env[
                "hotel.frontdesk.workspace"
            ].get_legacy_dashboard_data(property_id, business_date)
        prop = (
            self.env["hotel.property"].browse(property_id).exists()
            if property_id
            else self.env["hotel.property"]._get_default_property()
        )
        if not prop:
            raise UserError(_("Assign a default hotel property to your user."))
        prop.check_access("read")
        business_date = fields.Date.to_date(
            business_date or prop.get_business_date()
        )
        today_start, today_end = prop.get_business_day_bounds(business_date)
        property_domain = [("property_id", "=", prop.id)]
        rooms = self.env["hotel.room"].search(
            property_domain + [("active", "=", True)]
        )
        sellable = rooms.filtered("is_sellable")
        occupied = rooms.filtered(lambda room: room.occupancy_state == "occupied")
        board_reservations = self.search(
            [
                ("property_id", "=", prop.id),
                ("room_id", "!=", False),
                ("state", "in", ("confirmed", "checked_in")),
                ("checkin_date", "<", today_end),
                ("checkout_date", ">", today_start),
            ],
            order="state desc, checkin_date, id",
        )
        reservations_by_room = {}
        for reservation in board_reservations:
            existing = reservations_by_room.get(reservation.room_id.id)
            if not existing or reservation.state == "checked_in":
                reservations_by_room[reservation.room_id.id] = reservation
        board = []
        reserved_count = 0
        for room in rooms.sorted(lambda record: (record.floor_id.sequence, record.name)):
            reservation = reservations_by_room.get(room.id)
            if room.out_of_order:
                status = "out_of_order"
            elif room.admin_use:
                status = "house_use"
            elif reservation and reservation.state == "checked_in":
                status = "occupied"
            elif reservation:
                status = "reserved"
                reserved_count += 1
            elif room.hk_status == "dirty" or room.occupancy_state == "checkout":
                status = "dirty"
            else:
                status = "vacant"
            board.append(
                {
                    "room_id": room.id,
                    "room_name": room.name,
                    "floor_name": room.floor_id.name,
                    "room_type": room.room_type_id.display_name,
                    "status": status,
                    "reservation_id": reservation.id if reservation else False,
                    "reservation_name": reservation.name if reservation else False,
                    "guest_name": reservation.partner_id.name if reservation else False,
                    "arrival": fields.Datetime.to_string(reservation.checkin_date)
                    if reservation
                    else False,
                    "departure": fields.Datetime.to_string(reservation.checkout_date)
                    if reservation
                    else False,
                }
            )
        arrivals = self.search_count(
            [
                ("state", "=", "confirmed"),
                ("property_id", "=", prop.id),
                ("checkin_date", ">=", today_start),
                ("checkin_date", "<", today_end),
            ]
        )
        departures = self.search_count(
            [
                ("state", "=", "checked_in"),
                ("property_id", "=", prop.id),
                ("checkout_date", ">=", today_start),
                ("checkout_date", "<", today_end),
            ]
        )
        return {
            "property_id": prop.id,
            "property_name": prop.display_name,
            "business_date": fields.Date.to_string(business_date),
            "properties": [{"id": prop.id, "name": prop.company_id.display_name}],
            "total_rooms": len(rooms),
            "sellable_rooms": len(sellable),
            "occupied": len(occupied),
            "reserved": reserved_count,
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
            "in_house": self.search_count(
                [("property_id", "=", prop.id), ("state", "=", "checked_in")]
            ),
            "occupancy_pct": round(100 * len(occupied) / len(sellable), 1)
            if sellable
            else 0.0,
            "room_board": board,
        }
