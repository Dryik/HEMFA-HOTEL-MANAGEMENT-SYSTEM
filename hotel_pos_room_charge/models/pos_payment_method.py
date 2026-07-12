from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    is_room_charge = fields.Boolean(
        string="Charge to Room",
        help="Settling with this method posts the order to the in-house "
        "guest's folio instead of collecting money at the POS. The "
        "order's customer must be a checked-in hotel guest.",
    )
