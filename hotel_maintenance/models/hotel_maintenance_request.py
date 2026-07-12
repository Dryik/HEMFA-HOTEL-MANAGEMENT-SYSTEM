from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

REQUEST_STATES = [
    ("new", "New"),
    ("confirmed", "Confirmed"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
    ("verified", "Verified"),
    ("cancel", "Cancelled"),
]

# A blocking request in these states keeps the room out of order
# (blocking starts at confirmation, not at reporting).
BLOCKING_ACTIVE_STATES = ("confirmed", "in_progress", "done")


class HotelMaintenanceRequest(models.Model):
    """Custom room maintenance workflow.

    Request path (client requirement): guest/staff/housekeeping report
    to reception, a supervisor confirms, a technician executes, and the
    supervisor verifies before the room returns to service. A
    room-impacting request keeps the room out of sellable inventory
    until it is verified or cancelled.
    """

    _name = "hotel.maintenance.request"
    _description = "Hotel Maintenance Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "priority desc, id desc"

    name = fields.Char(
        string="Request Reference",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
    )
    room_id = fields.Many2one(
        "hotel.room",
        string="Room",
        index=True,
        tracking=True,
        help="Leave empty for common areas; use Location instead.",
    )
    location = fields.Char(
        help="Where the problem is when it is not inside a room "
        "(lobby, kitchen, elevator...).",
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        compute="_compute_property_id",
        store=True,
        readonly=False,
        precompute=True,
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )
    request_source = fields.Selection(
        [
            ("guest", "Guest"),
            ("staff", "Staff"),
            ("housekeeping", "Housekeeping"),
            ("inspection", "Inspection"),
        ],
        string="Reported By",
        default="staff",
        required=True,
        tracking=True,
    )
    reporter_partner_id = fields.Many2one(
        "res.partner",
        string="Reporting Guest",
        help="Guest who reported the problem, when the source is a guest.",
    )
    description = fields.Text(required=True)
    priority = fields.Selection(
        [
            ("0", "Low"),
            ("1", "Normal"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        default="1",
        required=True,
        tracking=True,
    )
    blocks_room = fields.Boolean(
        string="Blocks Room",
        tracking=True,
        help="The room cannot be sold while this request is open. "
        "Confirming the request takes the room out of order; "
        "verification returns it to service.",
    )
    technician_id = fields.Many2one(
        "res.users",
        string="Technician",
        tracking=True,
        domain=lambda self: [
            (
                "group_ids",
                "in",
                self.env.ref("hotel_base.group_hotel_maintenance").ids,
            )
        ],
    )
    state = fields.Selection(
        REQUEST_STATES,
        default="new",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    date_confirmed = fields.Datetime(string="Confirmed On", readonly=True)
    date_started = fields.Datetime(string="Started On", readonly=True)
    date_done = fields.Datetime(string="Done On", readonly=True)
    date_verified = fields.Datetime(string="Verified On", readonly=True)
    resolution_notes = fields.Text(
        help="What the technician actually did.",
    )

    @api.depends("room_id")
    def _compute_property_id(self):
        for rec in self:
            if rec.room_id:
                rec.property_id = rec.room_id.property_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "hotel.maintenance.request"
                    )
                    or _("New")
                )
        return super().create(vals_list)

    def write(self, vals):
        # Any change to the blocking flag, the room or the state must
        # resync out_of_order — including the room the request pointed
        # at before a room change.
        rooms_before = self.mapped("room_id")
        res = super().write(vals)
        if {"blocks_room", "room_id", "state"} & vals.keys():
            self._sync_room_block(rooms_before | self.mapped("room_id"))
        return res

    def unlink(self):
        for rec in self:
            if rec.state not in ("new", "cancel"):
                raise UserError(
                    _(
                        "Only new or cancelled maintenance requests can "
                        "be deleted."
                    )
                )
        return super().unlink()

    # -- state transitions -------------------------------------------

    def action_confirm(self):
        for rec in self:
            if rec.state != "new":
                raise UserError(_("Only new requests can be confirmed."))
            rec.write(
                {"state": "confirmed", "date_confirmed": fields.Datetime.now()}
            )

    def action_start(self):
        for rec in self:
            if rec.state != "confirmed":
                raise UserError(
                    _("Only confirmed requests can be started.")
                )
            vals = {
                "state": "in_progress",
                "date_started": fields.Datetime.now(),
            }
            if not rec.technician_id:
                vals["technician_id"] = self.env.uid
            rec.write(vals)

    def action_done(self):
        for rec in self:
            if rec.state != "in_progress":
                raise UserError(
                    _("Only in-progress requests can be marked done.")
                )
            rec.write({"state": "done", "date_done": fields.Datetime.now()})

    def action_verify(self):
        if not self.env.user.has_group("hotel_base.group_hotel_manager"):
            raise UserError(
                _("Only a manager can verify a maintenance request.")
            )
        for rec in self:
            if rec.state != "done":
                raise UserError(_("Only done requests can be verified."))
            rec.write(
                {"state": "verified", "date_verified": fields.Datetime.now()}
            )

    def action_cancel(self):
        for rec in self:
            if rec.state in ("verified",):
                raise UserError(
                    _("A verified request cannot be cancelled.")
                )
            rec.state = "cancel"

    def action_reset_new(self):
        for rec in self:
            if rec.state != "cancel":
                raise UserError(
                    _("Only cancelled requests can be reset to new.")
                )
            rec.state = "new"

    # -- room blocking -------------------------------------------------

    def _sync_room_block(self, rooms=None):
        """Keep room.out_of_order in line with open blocking requests."""
        for room in rooms if rooms is not None else self.mapped("room_id"):
            open_blocking = self.search_count(
                [
                    ("room_id", "=", room.id),
                    ("blocks_room", "=", True),
                    ("state", "in", BLOCKING_ACTIVE_STATES),
                ]
            )
            should_block = bool(open_blocking)
            if room.out_of_order != should_block:
                room.out_of_order = should_block

    @api.constrains("blocks_room", "room_id")
    def _check_blocking_needs_room(self):
        for rec in self:
            if rec.blocks_room and not rec.room_id:
                raise ValidationError(
                    _("A request can only block a room when a room is set.")
                )
