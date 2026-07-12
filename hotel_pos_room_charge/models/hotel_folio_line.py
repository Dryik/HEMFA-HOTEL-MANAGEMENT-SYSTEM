from odoo import fields, models


class HotelFolioLine(models.Model):
    _inherit = "hotel.folio.line"

    pos_order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        readonly=True,
        copy=False,
        index=True,
        help="POS order this charge came from, for the room-charge "
        "receipt and department reports.",
    )
