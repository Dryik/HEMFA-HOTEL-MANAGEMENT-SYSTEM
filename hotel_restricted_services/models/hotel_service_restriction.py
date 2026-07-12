from odoo import api, fields, models

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
    category_id = fields.Many2one(
        "product.category",
        string="Service Category",
        help="Leave empty to apply the ceiling to all services.",
    )
    daily_limit = fields.Monetary(
        string="Daily Limit per Guest",
        help="Maximum billed to the entity per guest folio per "
        "calendar day. Zero means no daily limit.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    active = fields.Boolean(default=True)

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
