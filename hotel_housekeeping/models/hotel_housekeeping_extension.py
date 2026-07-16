from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelHousekeepingTeam(models.Model):
    _name = "hotel.housekeeping.team"
    _description = "Hotel Housekeeping Team"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    leader_id = fields.Many2one("res.users", required=True)
    supervisor_id = fields.Many2one("res.users")
    member_ids = fields.Many2many("res.users", string="Team Members")
    active = fields.Boolean(default=True)

    _name_property_unique = models.Constraint(
        "unique (name, property_id)", "Housekeeping team names must be unique per hotel."
    )


class HotelHousekeepingChecklistItem(models.Model):
    _name = "hotel.housekeeping.checklist.item"
    _description = "Housekeeping Checklist Template Item"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    active = fields.Boolean(default=True)


class HotelHousekeepingTaskLine(models.Model):
    _name = "hotel.housekeeping.task.line"
    _description = "Housekeeping Task Checklist Result"
    _order = "sequence, id"

    task_id = fields.Many2one(
        "hotel.housekeeping.task", required=True, ondelete="cascade", index=True
    )
    item_id = fields.Many2one(
        "hotel.housekeeping.checklist.item", required=True, ondelete="restrict"
    )
    sequence = fields.Integer(related="item_id.sequence", store=True)
    done = fields.Boolean()
    note = fields.Char()

    _task_item_unique = models.Constraint(
        "unique (task_id, item_id)", "A checklist item may appear only once per task."
    )

    def write(self, vals):
        if self.mapped("task_id").filtered(lambda task: task.state in ("cleaned", "cancel")):
            raise UserError(_("Closed housekeeping checklists are immutable."))
        return super().write(vals)


class HotelHousekeepingTask(models.Model):
    _inherit = "hotel.housekeeping.task"

    reservation_id = fields.Many2one("hotel.reservation", ondelete="set null", index=True)
    trigger_type = fields.Selection(
        [
            ("prearrival", "Pre-arrival"),
            ("post_checkout", "Post-checkout"),
            ("guest_request", "Guest Request"),
            ("manual", "Manual"),
        ],
        default="manual",
        required=True,
        tracking=True,
    )
    source_key = fields.Char(readonly=True, copy=False, index=True)
    team_id = fields.Many2one("hotel.housekeeping.team", tracking=True)
    supervisor_id = fields.Many2one("res.users", tracking=True)
    scheduled_at = fields.Datetime(default=fields.Datetime.now, tracking=True)
    deadline = fields.Datetime(tracking=True)
    remarks = fields.Text()
    before_photo = fields.Image(max_width=1920, max_height=1080)
    after_photo = fields.Image(max_width=1920, max_height=1080)
    checklist_line_ids = fields.One2many(
        "hotel.housekeeping.task.line", "task_id", string="Checklist"
    )

    _source_key_unique = models.Constraint(
        "unique (source_key)", "A housekeeping workflow source may create only one task."
    )

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks.filtered(lambda record: not record.checklist_line_ids):
            items = self.env["hotel.housekeeping.checklist.item"].search(
                [("property_id", "=", task.property_id.id), ("active", "=", True)]
            )
            self.env["hotel.housekeeping.task.line"].sudo().create(
                [{"task_id": task.id, "item_id": item.id} for item in items]
            )
        return tasks

    @api.constrains("reservation_id", "room_id", "team_id")
    def _check_housekeeping_company(self):
        for task in self:
            if task.reservation_id and task.reservation_id.room_id != task.room_id:
                raise ValidationError(_("The housekeeping reservation must use the task room."))
            if task.team_id and task.team_id.property_id != task.property_id:
                raise ValidationError(_("The housekeeping team belongs to another hotel."))

    def action_complete(self):
        incomplete = self.mapped("checklist_line_ids").filtered(lambda line: not line.done)
        if incomplete:
            raise UserError(_("Complete every housekeeping checklist item first."))
        return super().action_complete()

    @api.model
    def _cron_create_prearrival_tasks(self):
        now = fields.Datetime.now()
        properties = self.env["hotel.property"].search([("active", "=", True)])
        for prop in properties:
            deadline = now + timedelta(hours=prop.prearrival_housekeeping_hours)
            reservations = self.env["hotel.reservation"].search(
                [
                    ("property_id", "=", prop.id),
                    ("state", "=", "confirmed"),
                    ("checkin_date", ">", now),
                    ("checkin_date", "<=", deadline),
                    ("room_id", "!=", False),
                ]
            )
            for reservation in reservations:
                source_key = f"prearrival:{reservation.id}"
                if self.search_count([("source_key", "=", source_key)]):
                    continue
                self.create(
                    {
                        "room_id": reservation.room_id.id,
                        "reservation_id": reservation.id,
                        "trigger_type": "prearrival",
                        "source_key": source_key,
                        "scheduled_at": now,
                        "deadline": reservation.checkin_date,
                        "priority": "2",
                    }
                )
        return True
