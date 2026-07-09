from odoo import fields, models


class HotelAmenity(models.Model):
    _name = "hotel.amenity"
    _description = "Room Amenity"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
