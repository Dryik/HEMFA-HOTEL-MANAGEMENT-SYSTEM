from odoo import _, api, fields, models
from odoo.exceptions import UserError

class HotelHousekeepingTask(models.Model):
    _name = "hotel.housekeeping.task"
    _description = "Housekeeping Cleaning Task"
    _inherit = ["mail.thread"]
    _order = "priority desc, date_assigned desc, id desc"

    name = fields.Char(
        string="Task Reference",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
    )
    room_id = fields.Many2one(
        "hotel.room",
        string="Room",
        required=True,
        index=True,
        tracking=True,
    )
    cleaner_id = fields.Many2one(
        "res.users",
        string="Assigned Cleaner",
        domain=lambda self: [("groups_id", "in", self.env.ref("hotel_base.group_hotel_housekeeping").id)],
        tracking=True,
    )
    inspector_id = fields.Many2one(
        "res.users",
        string="Inspector",
        domain=lambda self: [("groups_id", "in", (self.env.ref("hotel_base.group_hotel_fo_supervisor") + self.env.ref("hotel_base.group_hotel_manager")).ids)],
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("assigned", "Assigned"),
            ("cleaning", "Cleaning"),
            ("clean", "Cleaned"),
            ("inspected", "Inspected"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )
    priority = fields.Selection(
        [
            ("0", "Low"),
            ("1", "Normal"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        string="Priority",
        default="1",
        required=True,
        tracking=True,
    )
    date_assigned = fields.Datetime(string="Assigned Date", readonly=True)
    date_start = fields.Datetime(string="Started Date", readonly=True)
    date_completed = fields.Datetime(string="Completed Date", readonly=True)
    notes = fields.Text(string="Notes")

    property_id = fields.Many2one(
        "hotel.property",
        related="room_id.property_id",
        store=True,
        readonly=True,
    )
    room_type_id = fields.Many2one(
        "hotel.room.type",
        related="room_id.room_type_id",
        store=True,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.housekeeping.task")
                    or _("New")
                )
        return super().create(vals_list)

    def write(self, vals):
        if "cleaner_id" in vals and vals["cleaner_id"]:
            if not vals.get("state") or vals.get("state") == "draft":
                vals["state"] = "assigned"
            vals["date_assigned"] = fields.Datetime.now()
        return super().write(vals)

    def unlink(self):
        for task in self:
            if task.state not in ("draft", "cancel"):
                raise UserError(_("You can only delete housekeeping tasks in draft or cancelled state."))
        return super().unlink()

    def action_assign(self):
        self.ensure_one()
        if not self.cleaner_id:
            raise UserError(_("Please assign a cleaner first."))
        self.write({"state": "assigned", "date_assigned": fields.Datetime.now()})

    def action_start(self):
        self.ensure_one()
        if self.state not in ("draft", "assigned"):
            raise UserError(_("You can only start cleaning from Draft or Assigned states."))
        self.write({"state": "cleaning", "date_start": fields.Datetime.now()})

    def action_complete(self):
        self.ensure_one()
        if self.state != "cleaning":
            raise UserError(_("You can only mark a task as completed when it is in Cleaning state."))
        self.write({"state": "clean", "date_completed": fields.Datetime.now()})
        self.room_id.write({"hk_status": "clean"})

    def action_inspect(self):
        self.ensure_one()
        if self.state != "clean":
            raise UserError(_("You can only inspect a room after it is cleaned."))
        self.write({"state": "inspected", "inspector_id": self.env.user.id})
        self.room_id.write({"hk_status": "inspected"})

    def action_cancel(self):
        self.ensure_one()
        if self.state == "inspected":
            raise UserError(_("You cannot cancel a task that has already been inspected."))
        self.write({"state": "cancel"})
