from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

RESTRICTION_TYPES = [
    ("blocked", "Blocked"),
    ("limited", "Allowed with Limit"),
]


class HotelServiceRestriction(models.Model):
    """Per-stay service restriction line from the registration form.

    The legacy registration card lists which services the guest may or
    may not charge to the room (restaurant, laundry, minibar, ...) and
    an optional daily / whole-stay ceiling per service. Enforcement
    happens in hotel.folio.add_charge; manager override is logged in
    the folio chatter.
    """

    _name = "hotel.service.restriction"
    _description = "Guest Service Restriction"
    _order = "reservation_id, category_id"

    reservation_id = fields.Many2one(
        "hotel.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    category_id = fields.Many2one(
        "product.category",
        string="Service Category",
        required=True,
        help="Charges whose product belongs to this category (or a "
        "child of it) are restricted.",
    )
    restriction_type = fields.Selection(
        RESTRICTION_TYPES,
        string="Restriction",
        required=True,
        default="blocked",
    )
    daily_limit = fields.Monetary(
        string="Daily Limit",
        help="Maximum charge total per calendar day for this category. "
        "Zero means no daily limit.",
    )
    stay_limit = fields.Monetary(
        string="Stay Limit",
        help="Maximum charge total for the whole stay for this "
        "category. Zero means no stay limit.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="reservation_id.currency_id",
        store=True,
        readonly=True,
    )
    note = fields.Char(string="Reason / Note")

    _reservation_category_uniq = models.Constraint(
        "unique (reservation_id, category_id)",
        "Only one restriction per service category and reservation.",
    )

    def matches_product(self, product):
        """True when the product's category is this line's category or
        one of its descendants."""
        self.ensure_one()
        categ = product.categ_id
        if not categ:
            return False
        parent_ids = [
            int(pid) for pid in (categ.parent_path or "").split("/") if pid
        ]
        return self.category_id.id in parent_ids


class HotelEntityServiceCeiling(models.Model):
    """Per-entity (agency/company) service ceiling.

    Limits how much may be charged to the entity per guest per day, or
    for a category of services, regardless of the individual stay.
    """

    _name = "hotel.entity.service.ceiling"
    _description = "Entity Service Ceiling"
    _order = "partner_id, category_id"

    partner_id = fields.Many2one(
        "res.partner",
        string="Agency / Entity",
        required=True,
        ondelete="cascade",
        index=True,
        domain=[("is_hotel_agency", "=", True)],
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        index=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    category_id = fields.Many2one(
        "product.category",
        string="Service Category",
        help="Leave empty to apply the ceiling to all services.",
    )
    daily_limit = fields.Monetary(
        string="Daily Entity Limit",
        help="Maximum billed to the entity across all folios in this property "
        "and hotel business day. Zero means no daily limit.",
    )
    on_excess = fields.Selection(
        [
            ("block", "Block"),
            ("charge_guest", "Charge guest for excess"),
        ],
        string="On Excess",
        default="block",
        required=True,
        help="Block requires a Front Office Supervisor override to exceed the "
        "ceiling. Charge guest for excess keeps the allowed portion on the "
        "entity and bills the remainder to the stay's guest.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="property_id.company_id.currency_id",
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    _entity_property_category_uniq = models.Constraint(
        "unique (partner_id, property_id, category_id)",
        "Only one ceiling is allowed per entity, property, and service category.",
    )

    @api.constrains("partner_id", "property_id")
    def _check_company_consistency(self):
        for ceiling in self:
            if (
                ceiling.partner_id.company_id
                and ceiling.partner_id.company_id != ceiling.property_id.company_id
            ):
                raise ValidationError(
                    _("The entity and property must belong to the same company.")
                )

    @api.depends("partner_id", "category_id")
    def _compute_display_name(self):
        for rec in self:
            categ = rec.category_id.name or "All Services"
            rec.display_name = f"{rec.partner_id.name or ''}: {categ}"

    def matches_product(self, product):
        """True when the ceiling applies to this product (global
        ceilings match everything)."""
        self.ensure_one()
        if not self.category_id:
            return True
        categ = product.categ_id
        if not categ:
            return False
        parent_ids = [
            int(pid) for pid in (categ.parent_path or "").split("/") if pid
        ]
        return self.category_id.id in parent_ids
