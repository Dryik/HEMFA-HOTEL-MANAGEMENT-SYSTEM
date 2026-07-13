from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    hotel_property_ids = fields.Many2many(
        "hotel.property",
        "hotel_property_user_rel",
        "user_id",
        "property_id",
        string="Allowed Hotel Properties",
        domain="[('company_id', 'in', company_ids)]",
        help="Hotel records are restricted to these properties.",
    )
    default_hotel_property_id = fields.Many2one(
        "hotel.property",
        string="Default Hotel Property",
        domain="[('id', 'in', hotel_property_ids)]",
    )

    @api.constrains("hotel_property_ids", "default_hotel_property_id")
    def _check_default_hotel_property(self):
        for user in self:
            if user.hotel_property_ids.filtered(
                lambda prop: prop.company_id not in user.company_ids
            ):
                raise ValidationError(
                    _("Assigned hotel properties must belong to the user's allowed companies.")
                )
            if (
                user.default_hotel_property_id
                and user.default_hotel_property_id not in user.hotel_property_ids
            ):
                raise ValidationError(
                    _("The default hotel property must be one of the allowed properties.")
                )
