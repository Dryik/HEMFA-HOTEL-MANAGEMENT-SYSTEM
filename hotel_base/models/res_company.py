from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    hotel_property_config_id = fields.Many2one(
        "hotel.property",
        string="Hotel Configuration",
        compute="_compute_hotel_property_config_id",
        search="_search_hotel_property_config_id",
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
    hotel_type = fields.Selection(
        related="hotel_property_config_id.hotel_type", readonly=False
    )
    hotel_tagline = fields.Char(
        related="hotel_property_config_id.tagline", readonly=False
    )
    hotel_website_description = fields.Html(
        related="hotel_property_config_id.website_description", readonly=False
    )
    hotel_website_policy = fields.Html(
        related="hotel_property_config_id.website_policy", readonly=False
    )
    hotel_website_banner = fields.Image(
        related="hotel_property_config_id.website_banner", readonly=False
    )
    hotel_website_gallery_attachment_ids = fields.Many2many(
        related="hotel_property_config_id.website_gallery_attachment_ids",
        readonly=False,
    )
    hotel_website_published = fields.Boolean(
        related="hotel_property_config_id.website_published", readonly=False
    )
    hotel_website_review_limit = fields.Integer(
        related="hotel_property_config_id.website_review_limit", readonly=False
    )
    hotel_stay_charge_policy = fields.Selection(
        related="hotel_property_config_id.stay_charge_policy", readonly=False
    )
    hotel_online_payment_policy = fields.Selection(
        related="hotel_property_config_id.online_payment_policy", readonly=False
    )
    hotel_online_deposit_value = fields.Float(
        related="hotel_property_config_id.online_deposit_value", readonly=False
    )
    hotel_online_hold_minutes = fields.Integer(
        related="hotel_property_config_id.online_hold_minutes", readonly=False
    )
    hotel_prearrival_housekeeping_hours = fields.Integer(
        related="hotel_property_config_id.prearrival_housekeeping_hours", readonly=False
    )
    hotel_adult_age_min = fields.Integer(
        related="hotel_property_config_id.adult_age_min", readonly=False
    )
    hotel_teenager_age_min = fields.Integer(
        related="hotel_property_config_id.teenager_age_min", readonly=False
    )
    hotel_teenager_age_max = fields.Integer(
        related="hotel_property_config_id.teenager_age_max", readonly=False
    )
    hotel_child_age_min = fields.Integer(
        related="hotel_property_config_id.child_age_min", readonly=False
    )
    hotel_child_age_max = fields.Integer(
        related="hotel_property_config_id.child_age_max", readonly=False
    )
    hotel_infant_age_max = fields.Integer(
        related="hotel_property_config_id.infant_age_max", readonly=False
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

    @api.model_create_multi
    def create(self, vals_list):
        # The hotel operational settings are related fields onto a per-company
        # hotel.property that does not exist yet while a brand-new company is
        # being entered. On such a form those fields render as 0/empty, and
        # writing them straight through on create would push an invalid value
        # (e.g. online_hold_minutes = 0) into the auto-created property and trip
        # its validation. Hold the hotel_* values aside, let the company (and
        # its default-valued property) come into being, then re-apply only the
        # values the user actually set.
        hotel_field_names = self._hotel_related_field_names()
        held_values = []
        for vals in vals_list:
            held_values.append(
                {name: vals.pop(name) for name in hotel_field_names if name in vals}
            )
        companies = super().create(vals_list)
        for company, held in zip(companies, held_values):
            meaningful = {
                name: value
                for name, value in held.items()
                if value not in (0, 0.0, False, "")
            }
            if meaningful:
                company.write(meaningful)
        return companies

    @api.model
    def _hotel_related_field_names(self):
        return [
            name
            for name in self._fields
            if name.startswith("hotel_") and name != "hotel_property_config_id"
        ]

    def _without_unchanged_hotel_values(self, vals):
        """Drop hotel-field echoes from a mixed company/settings save.

        The company form can send unchanged writable related fields together
        with an ordinary company edit. Rewriting an unchanged legacy value such
        as online_hold_minutes = 0 needlessly invokes hotel.property constraints
        and blocks an otherwise unrelated company rename.
        """
        values = dict(vals)
        if not any(not name.startswith("hotel_") for name in values):
            return values

        for name in self._hotel_related_field_names():
            if name not in values or self._fields[name].type in {
                "many2many",
                "one2many",
            }:
                continue
            if all(company[name] == values[name] for company in self):
                values.pop(name)
        return values

    @api.model
    def _search_hotel_property_config_id(self, operator, value):
        """Map the private hotel configuration back to its Odoo company."""
        if operator not in {"in", "not in"}:
            return NotImplemented

        try:
            property_ids = list(value)
        except TypeError:
            property_ids = [value]
        property_ids = [property_id for property_id in property_ids if property_id]
        company_ids = (
            self.env["hotel.property"]
            .sudo()
            .browse(property_ids)
            .exists()
            .mapped("company_id")
            .ids
        )
        return [("id", operator, company_ids)]

    def write(self, vals):
        mixed_company_write = any(not name.startswith("hotel_") for name in vals)
        vals = self._without_unchanged_hotel_values(vals)

        # Older databases may contain the zero value written by the company
        # form before the create-path guard existed. Repair it before an
        # ordinary company save; a genuinely new zero value remains in ``vals``
        # and is still rejected by hotel.property's validation constraint.
        if mixed_company_write:
            invalid_hold_properties = self.env["hotel.property"].sudo().search(
                [
                    ("company_id", "in", self.ids),
                    ("online_hold_minutes", "<=", 0),
                ]
            )
            if invalid_hold_properties:
                invalid_hold_properties.write({"online_hold_minutes": 15})

        manager_group = self.env.ref(
            "hotel_base.group_hotel_manager", raise_if_not_found=False
        )
        if (
            vals
            and all(name.startswith("hotel_") for name in vals)
            and manager_group
            and manager_group in self.env.user.group_ids
        ):
            result = super(ResCompany, self.sudo()).write(vals)
        else:
            result = super().write(vals)
        if {"name", "partner_id"}.intersection(vals):
            properties = self.env["hotel.property"].sudo().search(
                [("company_id", "in", self.ids)]
            )
            for property_rec in properties:
                property_rec.write(
                    {
                        "name": property_rec.company_id.name,
                        "address_id": property_rec.company_id.partner_id.id,
                    }
                )
        return result
