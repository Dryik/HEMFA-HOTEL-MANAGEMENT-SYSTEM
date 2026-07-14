from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain


class HotelLostFound(models.Model):
    _name = "hotel.lost.found"
    _description = "Hotel Lost and Found Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "found_at desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    room_id = fields.Many2one(
        "hotel.room", domain="[('property_id', '=', property_id)]"
    )
    reservation_id = fields.Many2one(
        "hotel.reservation",
        domain="[('property_id', '=', property_id)]",
        groups="hotel_base.group_hotel_frontdesk",
    )
    item_name = fields.Char(required=True)
    description = fields.Text(required=True)
    found_at = fields.Datetime(required=True, default=fields.Datetime.now)
    found_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    storage_location = fields.Char(required=True)
    claimant_id = fields.Many2one(
        "res.partner",
        string="Claimed By",
        groups="hotel_base.group_hotel_frontdesk",
    )
    resolved_at = fields.Datetime(readonly=True, copy=False)
    resolved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    resolution_reason = fields.Text(copy=False)
    state = fields.Selection(
        [("found", "Found"), ("claimed", "Claimed"), ("disposed", "Disposed")],
        default="found",
        required=True,
        readonly=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and (
                vals.get("state", "found") != "found"
                or vals.get("resolved_at")
                or vals.get("resolved_by_id")
            ):
                raise UserError(_("Lost-and-found status must change through its actions."))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.lost.found")
                    or _("New")
                )
        return super().create(vals_list)

    @api.constrains("property_id", "room_id", "reservation_id")
    def _check_property_consistency(self):
        for item in self:
            if item.room_id and item.room_id.property_id != item.property_id:
                raise ValidationError(_("The room must belong to the active company."))
            if item.reservation_id and item.reservation_id.property_id != item.property_id:
                raise ValidationError(_("The stay must belong to the active company."))

    def action_mark_claimed(self):
        for item in self:
            if item.state != "found" or not item.claimant_id:
                raise UserError(_("Select a claimant on a currently found item."))
            item._write_resolution(
                {
                    "state": "claimed",
                    "resolved_at": fields.Datetime.now(),
                    "resolved_by_id": self.env.user.id,
                }
            )
        return True

    def action_dispose(self):
        for item in self:
            if item.state != "found" or not (item.resolution_reason or "").strip():
                raise UserError(_("A disposal reason is required for a found item."))
            item._write_resolution(
                {
                    "state": "disposed",
                    "resolved_at": fields.Datetime.now(),
                    "resolved_by_id": self.env.user.id,
                }
            )
        return True

    def _write_resolution(self, values):
        return super(HotelLostFound, self).write(values)

    def write(self, vals):
        if (
            "state" in vals
            and any(item.state != vals["state"] for item in self)
        ):
            raise UserError(
                _("Lost-and-found status can only be changed through its actions.")
            )
        if (
            self.filtered(lambda item: item.state != "found")
        ):
            raise UserError(_("Resolved lost-and-found records are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda item: item.state != "found"):
            raise UserError(_("Resolved lost-and-found records cannot be deleted."))
        return super().unlink()


class HotelDoNotDisturb(models.Model):
    _name = "hotel.do.not.disturb"
    _description = "Hotel Do Not Disturb Request"
    _order = "start_at desc, id desc"

    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    reservation_id = fields.Many2one(
        "hotel.reservation",
        required=True,
        domain="[('property_id', '=', property_id), ('state', '=', 'checked_in')]",
        groups="hotel_base.group_hotel_frontdesk",
    )
    room_id = fields.Many2one(related="reservation_id.room_id", store=True)
    start_at = fields.Datetime(required=True, default=fields.Datetime.now)
    end_at = fields.Datetime()
    note = fields.Char()
    state = fields.Selection(
        [("active", "Active"), ("ended", "Ended"), ("cancelled", "Cancelled")],
        default="active",
        required=True,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(
            vals.get("state", "active") != "active" for vals in vals_list
        ):
            raise UserError(_("DND status must change through its actions."))
        return super().create(vals_list)

    @api.constrains("property_id", "reservation_id", "start_at", "end_at")
    def _check_dnd_values(self):
        for request in self:
            if request.reservation_id.property_id != request.property_id:
                raise ValidationError(_("The DND request and stay must use the same property."))
            if request.end_at and request.end_at <= request.start_at:
                raise ValidationError(_("DND end time must be after its start time."))

    def action_end(self):
        now = fields.Datetime.now()
        for request in self.filtered(lambda record: record.state == "active"):
            end_at = max(now, request.start_at + timedelta(seconds=1))
            request._write_transition({"state": "ended", "end_at": end_at})
        return True

    def action_cancel(self):
        self.filtered(lambda request: request.state == "active")._write_transition(
            {"state": "cancelled"}
        )
        return True

    def _write_transition(self, values):
        return super(HotelDoNotDisturb, self).write(values)

    def write(self, vals):
        if (
            "state" in vals
            and any(request.state != vals["state"] for request in self)
        ):
            raise UserError(_("DND status can only be changed through its actions."))
        if self.filtered(lambda request: request.state != "active"):
            raise UserError(_("Ended DND requests are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda request: request.state != "active"):
            raise UserError(_("Ended DND requests cannot be deleted."))
        return super().unlink()


class HotelWakeupCall(models.Model):
    _name = "hotel.wakeup.call"
    _description = "Hotel Wake-up Call"
    _inherit = ["mail.activity.mixin"]
    _order = "scheduled_at, id"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    reservation_id = fields.Many2one(
        "hotel.reservation",
        required=True,
        domain="[('property_id', '=', property_id), ('state', '=', 'checked_in')]",
    )
    room_id = fields.Many2one(related="reservation_id.room_id", store=True)
    scheduled_at = fields.Datetime(required=True, index=True)
    assigned_user_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    completed_at = fields.Datetime(readonly=True, copy=False)
    completion_note = fields.Text()
    urgency = fields.Selection(
        [
            ("overdue", "Overdue"),
            ("upcoming", "Next 60 Minutes"),
            ("later", "Later"),
            ("closed", "Closed"),
        ],
        string="Urgency",
        compute="_compute_operational_status",
        search="_search_urgency",
    )
    scheduled_today = fields.Boolean(
        string="Scheduled Today",
        compute="_compute_operational_status",
        search="_search_scheduled_today",
    )
    state = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("completed", "Completed"),
            ("missed", "Missed"),
            ("cancelled", "Cancelled"),
        ],
        default="scheduled",
        required=True,
        readonly=True,
    )

    @api.depends("scheduled_at", "state", "property_id.timezone")
    def _compute_operational_status(self):
        now = fields.Datetime.now()
        next_hour = now + timedelta(hours=1)
        bounds_by_property = {}
        for call in self:
            bounds = bounds_by_property.get(call.property_id.id)
            if not bounds:
                bounds = self._property_calendar_day_bounds(call.property_id, now)
                bounds_by_property[call.property_id.id] = bounds
            call.scheduled_today = bool(
                call.scheduled_at
                and bounds[0] <= call.scheduled_at < bounds[1]
            )
            if not call.scheduled_at:
                call.urgency = False
            elif call.state != "scheduled":
                call.urgency = "closed"
            elif call.scheduled_at < now:
                call.urgency = "overdue"
            elif call.scheduled_at <= next_hour:
                call.urgency = "upcoming"
            else:
                call.urgency = "later"

    @api.model
    def _context_property(self):
        property_id = self.env.context.get("hotel_property_id")
        if property_id:
            try:
                property_id = int(property_id)
            except (TypeError, ValueError):
                property_id = False
            prop = self.env["hotel.property"].browse(property_id).exists()
            if prop and prop.company_id in self.env.companies:
                prop.check_access("read")
                return prop
        return self.env["hotel.property"]._get_default_property()

    @api.model
    def _property_calendar_day_bounds(self, prop, moment=None):
        """Return property-local midnight bounds as naive UTC datetimes."""
        moment = fields.Datetime.to_datetime(moment or fields.Datetime.now())
        utc_moment = pytz.UTC.localize(moment) if moment.tzinfo is None else moment
        timezone = pytz.timezone(prop.timezone or "UTC")
        local_date = utc_moment.astimezone(timezone).date()

        def local_midnight(day):
            value = datetime.combine(day, time.min)
            try:
                localized = timezone.localize(value, is_dst=None)
            except pytz.NonExistentTimeError:
                localized = timezone.localize(value, is_dst=True)
            except pytz.AmbiguousTimeError:
                localized = timezone.localize(value, is_dst=False)
            return localized.astimezone(pytz.UTC).replace(tzinfo=None)

        return local_midnight(local_date), local_midnight(local_date + timedelta(days=1))

    @api.model
    def _search_scheduled_today(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            return NotImplemented
        prop = self._context_property()
        if not prop:
            return Domain.FALSE if (operator == "=") == value else Domain.TRUE
        start, end = self._property_calendar_day_bounds(prop)
        domain = Domain.AND(
            [
                Domain("scheduled_at", ">=", start),
                Domain("scheduled_at", "<", end),
            ]
        )
        return domain if (operator == "=") == value else ~domain

    @api.model
    def _search_urgency(self, operator, value):
        supported = {"overdue", "upcoming", "later", "closed"}
        if operator in ("=", "!="):
            values = {value}
        elif operator in ("in", "not in"):
            values = set(value)
        else:
            return NotImplemented
        if not values <= supported:
            return Domain.TRUE if operator in ("!=", "not in") else Domain.FALSE

        now = fields.Datetime.now()
        next_hour = now + timedelta(hours=1)
        domains = {
            "overdue": Domain.AND(
                [Domain("state", "=", "scheduled"), Domain("scheduled_at", "<", now)]
            ),
            "upcoming": Domain.AND(
                [
                    Domain("state", "=", "scheduled"),
                    Domain("scheduled_at", ">=", now),
                    Domain("scheduled_at", "<=", next_hour),
                ]
            ),
            "later": Domain.AND(
                [
                    Domain("state", "=", "scheduled"),
                    Domain("scheduled_at", ">", next_hour),
                ]
            ),
            "closed": Domain("state", "!=", "scheduled"),
        }
        domain = Domain.OR([domains[item] for item in values])
        return domain if operator in ("=", "in") else ~domain

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and (
                vals.get("state", "scheduled") != "scheduled"
                or vals.get("completed_at")
            ):
                raise UserError(_("Wake-up call status must change through its actions."))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.wakeup.call")
                    or _("New")
                )
        return super().create(vals_list)

    @api.constrains("property_id", "reservation_id")
    def _check_property_consistency(self):
        for call in self:
            if call.reservation_id.property_id != call.property_id:
                raise ValidationError(_("The wake-up call and stay must use the same property."))

    def action_complete(self):
        self.filtered(lambda call: call.state == "scheduled")._write_transition(
            {"state": "completed", "completed_at": fields.Datetime.now()}
        )
        return True

    def action_missed(self):
        self.filtered(lambda call: call.state == "scheduled")._write_transition(
            {"state": "missed", "completed_at": fields.Datetime.now()}
        )
        return True

    def action_cancel(self):
        self.filtered(lambda call: call.state == "scheduled")._write_transition(
            {"state": "cancelled"}
        )
        return True

    def _write_transition(self, values):
        return super(HotelWakeupCall, self).write(values)

    def write(self, vals):
        if (
            "state" in vals
            and any(call.state != vals["state"] for call in self)
        ):
            raise UserError(
                _("Wake-up call status can only be changed through its actions.")
            )
        if self.filtered(lambda call: call.state != "scheduled"):
            raise UserError(_("Completed wake-up calls are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda call: call.state != "scheduled"):
            raise UserError(_("Completed wake-up calls cannot be deleted."))
        return super().unlink()
