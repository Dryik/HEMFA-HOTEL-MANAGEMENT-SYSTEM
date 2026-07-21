from odoo import fields, models
from odoo.tools import frozendict


class ResUsers(models.Model):
    _inherit = "res.users"

    def context_get(self):
        """Seed hotel actions from Odoo's authoritative active company."""
        context = dict(super().context_get())
        user = self.env.user
        hotel_groups = (
            "hotel_base.group_hotel_frontdesk",
            "hotel_base.group_hotel_housekeeping",
            "hotel_base.group_hotel_maintenance",
            "hotel_base.group_hotel_fb",
            "hotel_base.group_hotel_accountant",
        )
        if not (self.env.su or any(user.has_group(group) for group in hotel_groups)):
            return frozendict(context)
        prop = self.env["hotel.property"]._get_default_property()
        if prop:
            context.update(
                {
                    "hotel_property_id": prop.id,
                    "hotel_business_date": fields.Date.to_string(
                        prop.get_business_date()
                    ),
                }
            )
        return frozendict(context)
