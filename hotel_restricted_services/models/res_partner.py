from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    service_ceiling_ids = fields.One2many(
        "hotel.entity.service.ceiling",
        "partner_id",
        string="Service Ceilings",
    )
