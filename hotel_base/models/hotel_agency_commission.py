from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelAgencyCommission(models.Model):
    """Company-level commission configuration placeholder.

    This deliberately stores only the agreed commercial terms. It does not
    accrue, settle, or post commission accounting entries.
    """

    _name = "hotel.agency.commission"
    _description = "Hotel Agency Commission Configuration"
    _rec_name = "agency_id"
    _order = "property_id, agency_id"

    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        index=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    agency_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain=[("is_hotel_agency", "=", True)],
    )
    commission_type = fields.Selection(
        [
            ("none", "No Commission"),
            ("percent", "Percentage Placeholder"),
            ("fixed", "Fixed Amount Placeholder"),
        ],
        required=True,
        default="none",
    )
    commission_rate = fields.Float(string="Commission %", digits=(16, 4))
    commission_amount = fields.Monetary()
    currency_id = fields.Many2one(
        related="property_id.company_id.currency_id", store=True, readonly=True
    )
    notes = fields.Text(
        help="Commercial notes only. Commission settlement is intentionally deferred."
    )
    active = fields.Boolean(default=True)

    _property_agency_unique = models.Constraint(
        "unique (property_id, agency_id)",
        "Only one commission configuration is allowed per agency and property.",
    )

    @api.constrains(
        "property_id",
        "agency_id",
        "commission_type",
        "commission_rate",
        "commission_amount",
    )
    def _check_commission_configuration(self):
        for configuration in self:
            if not configuration.agency_id.is_hotel_agency:
                raise ValidationError(
                    _("Commission configuration requires an agency or entity.")
                )
            if (
                configuration.agency_id.company_id
                and configuration.agency_id.company_id
                != configuration.property_id.company_id
            ):
                raise ValidationError(
                    _("The agency and property must belong to the same company.")
                )
            if configuration.commission_type == "percent" and not (
                0.0 <= configuration.commission_rate <= 100.0
            ):
                raise ValidationError(
                    _("Commission percentage must be between 0 and 100.")
                )
            if (
                configuration.commission_type == "fixed"
                and configuration.commission_amount < 0.0
            ):
                raise ValidationError(
                    _("Fixed commission amount cannot be negative.")
                )


class ResPartner(models.Model):
    _inherit = "res.partner"

    hotel_commission_ids = fields.One2many(
        "hotel.agency.commission",
        "agency_id",
        string="Hotel Commission Placeholders",
        groups="hotel_base.group_hotel_frontdesk,hotel_base.group_hotel_accountant",
    )
