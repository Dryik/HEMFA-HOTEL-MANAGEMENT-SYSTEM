from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelHousekeepingTask(models.Model):
    _name = "hotel.housekeeping.task"
    _description = "Housekeeping Cleaning Task"
    _inherit = ["mail.thread"]
    _order = "priority desc, id desc"

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
        string="Cleaner",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("cleaning", "Cleaning"),
            ("cleaned", "Cleaned"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="new",
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
    date_start = fields.Datetime(string="Started", readonly=True)
    date_completed = fields.Datetime(string="Completed", readonly=True)
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

    def unlink(self):
        for task in self:
            if task.state not in ("new", "cancel"):
                raise UserError(_("You can only delete housekeeping tasks that are new or cancelled."))
        return super().unlink()

    def action_start(self):
        self.ensure_one()
        if self.state != "new":
            raise UserError(_("You can only start a new task."))
        vals = {"state": "cleaning", "date_start": fields.Datetime.now()}
        if not self.cleaner_id:
            vals["cleaner_id"] = self.env.uid
        self.write(vals)

    def action_complete(self):
        self.ensure_one()
        if self.state != "cleaning":
            raise UserError(_("You can only mark a task as cleaned when it is in cleaning state."))
        self.write({"state": "cleaned", "date_completed": fields.Datetime.now()})
        self.room_id.write({"hk_status": "clean"})

    def action_cancel(self):
        self.ensure_one()
        if self.state == "cleaned":
            raise UserError(_("You cannot cancel a task that is already cleaned."))
        self.write({"state": "cancel"})
