from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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
                raise ValidationError(_("The room must belong to the selected property."))
            if item.reservation_id and item.reservation_id.property_id != item.property_id:
                raise ValidationError(_("The stay must belong to the selected property."))

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
        self.filtered(lambda request: request.state == "active")._write_transition(
            {"state": "ended", "end_at": fields.Datetime.now()}
        )
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
