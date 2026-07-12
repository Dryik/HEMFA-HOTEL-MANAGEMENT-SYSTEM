from odoo import fields, models


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    service_restriction_ids = fields.One2many(
        "hotel.service.restriction",
        "reservation_id",
        string="Service Restrictions",
    )
