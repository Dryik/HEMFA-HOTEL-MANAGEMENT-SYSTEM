from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelFloor(models.Model):
    _name = "hotel.floor"
    _description = "Hotel Floor"
    _order = "property_id, sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        ondelete="cascade",
        index=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    room_ids = fields.One2many("hotel.room", "floor_id", string="Rooms")
    active = fields.Boolean(default=True)
    retired_at = fields.Datetime(readonly=True, copy=False)
    retirement_reason = fields.Text(copy=False)

    _name_property_uniq = models.Constraint(
        "unique (name, property_id)",
        "Floor name must be unique per property.",
    )

    def write(self, values):
        if values.get("active") is False and self.mapped("room_ids").filtered("active"):
            raise UserError(_("Retire or move all active rooms before retiring a floor."))
        if "active" in values:
            values = dict(values)
            values["retired_at"] = (
                False if values["active"] else fields.Datetime.now()
            )
            if values["active"]:
                values["retirement_reason"] = False
        return super().write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise UserError(_("Floors cannot be deleted. Archive unused floors instead."))
