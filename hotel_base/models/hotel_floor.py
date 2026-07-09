from odoo import fields, models


class HotelFloor(models.Model):
    _name = "hotel.floor"
    _description = "Hotel Floor"
    _order = "property_id, sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "hotel.property", required=True, ondelete="cascade", index=True
    )
    room_ids = fields.One2many("hotel.room", "floor_id", string="Rooms")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "name_property_uniq",
            "unique(name, property_id)",
            "Floor name must be unique per property.",
        ),
    ]
