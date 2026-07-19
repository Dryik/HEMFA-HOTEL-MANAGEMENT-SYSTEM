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
    pos_order_line_id = fields.Many2one(
        "pos.order.line", string="POS Order Line", readonly=True, copy=False, index=True
    )

    _pos_order_line_uniq = models.Constraint(
        "unique (pos_order_line_id, payee_partner_id)",
        "A POS order line can be transferred to a folio only once.",
    )
