from odoo import fields, models


class HotelProperty(models.Model):
    _inherit = "hotel.property"

    current_business_date = fields.Date(
        string="Current Business Date",
        default=fields.Date.today,
        help="The active operational business date for the hotel, rolled forward daily by the night audit.",
    )
