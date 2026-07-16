from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelProperty(models.Model):
    _inherit = "hotel.property"

    website_id = fields.Many2one(
        "website",
        string="Hotel Website",
        domain="[('company_id', '=', company_id)]",
        ondelete="restrict",
    )
    website_ready = fields.Boolean(compute="_compute_website_readiness")
    website_readiness_message = fields.Text(compute="_compute_website_readiness")

    def _website_readiness_errors(self):
        self.ensure_one()
        errors = []
        if not self.website_id:
            errors.append(_("Select the Odoo website for this hotel company."))
        if not self.website_description:
            errors.append(_("Add the hotel website description."))
        if not self.website_policy:
            errors.append(_("Add the public hotel policies."))
        if not self.env["hotel.room.type"].sudo().search_count(
            [
                ("property_id", "=", self.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ]
        ):
            errors.append(_("Publish at least one room type."))
        if not self.env["hotel.room"].sudo().search_count(
            [
                ("property_id", "=", self.id),
                ("is_sellable", "=", True),
                ("website_published", "=", True),
            ]
        ):
            errors.append(_("Publish at least one sellable physical room."))
        if not self.env["hotel.document.type"].sudo().search_count(
            [
                ("property_id", "=", self.id),
                ("active", "=", True),
                ("required_for_website", "=", True),
            ]
        ):
            errors.append(_("Configure at least one website document type."))
        if not self.env["product.pricelist"].sudo().search_count(
            [
                ("active", "=", True),
                ("hotel_website_published", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ]
        ):
            errors.append(_("Configure an active hotel pricelist."))
        if self.online_payment_policy != "manual" and not self.env[
            "payment.provider"
        ].sudo().search_count(
            [
                ("company_id", "=", self.company_id.id),
                ("state", "in", ("enabled", "test")),
            ]
        ):
            errors.append(_("Enable an online payment provider for this company."))
        return errors

    @api.depends(
        "website_id",
        "website_description",
        "website_policy",
        "online_payment_policy",
        "company_id",
    )
    def _compute_website_readiness(self):
        for property_rec in self:
            errors = property_rec._website_readiness_errors()
            property_rec.website_ready = not errors
            property_rec.website_readiness_message = "\n".join(errors)

    @api.constrains("website_published")
    def _check_website_publication_readiness(self):
        for property_rec in self.filtered("website_published"):
            errors = property_rec._website_readiness_errors()
            if errors:
                raise ValidationError(
                    _("The hotel website is not ready to publish:\n- %s")
                    % "\n- ".join(errors)
                )

    @api.constrains("website_id", "company_id")
    def _check_hotel_website_company(self):
        for property_rec in self.filtered("website_id"):
            if property_rec.website_id.company_id != property_rec.company_id:
                raise ValidationError(_("The hotel website must use the hotel company."))


class ResCompany(models.Model):
    _inherit = "res.company"

    hotel_website_ready = fields.Boolean(
        related="hotel_property_config_id.website_ready", readonly=True
    )
    hotel_website_id = fields.Many2one(
        related="hotel_property_config_id.website_id", readonly=False
    )
    hotel_website_readiness_message = fields.Text(
        related="hotel_property_config_id.website_readiness_message", readonly=True
    )


class WebsiteMenu(models.Model):
    _inherit = "website.menu"

    @api.depends("page_id", "is_mega_menu", "child_id", "website_id")
    def _compute_visible(self):
        super()._compute_visible()
        hotel_menus = self.filtered(
            lambda menu: menu.website_id
            and (
                (menu.url or "").startswith("/hotel")
                or any((child.url or "").startswith("/hotel") for child in menu.child_id)
            )
        )
        if not hotel_menus:
            return
        published_websites = set(
            self.env["hotel.property"]
            .sudo()
            .search(
                [
                    ("website_id", "in", hotel_menus.website_id.ids),
                    ("active", "=", True),
                    ("website_published", "=", True),
                ]
            )
            .mapped("website_id")
            .ids
        )
        for menu in hotel_menus:
            menu.is_visible = menu.is_visible and menu.website_id.id in published_websites
