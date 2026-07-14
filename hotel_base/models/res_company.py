from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    hotel_property_config_id = fields.Many2one(
        "hotel.property",
        string="Hotel Configuration",
        compute="_compute_hotel_property_config_id",
        compute_sudo=True,
    )
    hotel_day_start_hour = fields.Float(
        string="Business Day Start",
        related="hotel_property_config_id.day_start_hour",
        readonly=False,
    )
    hotel_timezone = fields.Selection(
        string="Hotel Timezone",
        related="hotel_property_config_id.timezone",
        readonly=False,
    )
    hotel_late_checkout_grace_hours = fields.Float(
        string="Late Checkout Grace (hours)",
        related="hotel_property_config_id.late_checkout_grace_hours",
        readonly=False,
    )
    hotel_cancellation_policy = fields.Selection(
        string="Cancellation Policy",
        related="hotel_property_config_id.cancellation_policy",
        readonly=False,
    )
    hotel_cancellation_grace_hours = fields.Float(
        string="Cancellation Grace (hours)",
        related="hotel_property_config_id.cancellation_grace_hours",
        readonly=False,
    )
    hotel_cancellation_fee_value = fields.Float(
        string="Cancellation Fee / Percentage",
        related="hotel_property_config_id.cancellation_fee_value",
        readonly=False,
    )
    hotel_no_show_policy = fields.Selection(
        string="No-show Policy",
        related="hotel_property_config_id.no_show_policy",
        readonly=False,
    )
    hotel_no_show_grace_hours = fields.Float(
        string="No-show Grace (hours)",
        related="hotel_property_config_id.no_show_grace_hours",
        readonly=False,
    )
    hotel_no_show_fee_value = fields.Float(
        string="No-show Fee / Percentage",
        related="hotel_property_config_id.no_show_fee_value",
        readonly=False,
    )

    @api.depends("name")
    def _compute_hotel_property_config_id(self):
        properties = self.env["hotel.property"].sudo().with_context(
            active_test=False
        ).search(
            [("company_id", "in", self.ids)],
            order="active desc, id",
        )
        by_company = {}
        for prop in properties:
            by_company.setdefault(prop.company_id.id, prop)
        for company in self:
            prop = by_company.get(company.id)
            if not prop and company.id:
                prop = self.env["hotel.property"].sudo().create(
                    {
                        "name": company.name,
                        "code": str(company.id),
                        "company_id": company.id,
                        "address_id": company.partner_id.id,
                        "timezone": self.env.user.tz or "Africa/Tripoli",
                    }
                )
                by_company[company.id] = prop
            company.hotel_property_config_id = prop

    def write(self, vals):
        manager_group = self.env.ref(
            "hotel_base.group_hotel_manager", raise_if_not_found=False
        )
        if (
            vals
            and all(name.startswith("hotel_") for name in vals)
            and manager_group
            and manager_group in self.env.user.group_ids
        ):
            return super(ResCompany, self.sudo()).write(vals)
        return super().write(vals)
