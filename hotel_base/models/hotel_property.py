from odoo import api, fields, models


class HotelProperty(models.Model):
    _name = "hotel.property"
    _description = "Hotel Property"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(help="Short code used in references and reports.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    address_id = fields.Many2one(
        "res.partner",
        string="Address",
        domain=[("is_company", "=", True)],
    )
    # Hotel business day: charges run noon to noon (client requirement).
    day_start_hour = fields.Float(
        string="Business Day Start",
        default=12.0,
        tracking=True,
        help="Hour at which the hotel business day rolls over. "
        "A stay is charged per business day from this hour to the same "
        "hour the next calendar day.",
    )
    late_checkout_grace_hours = fields.Float(
        string="Late Checkout Grace (hours)",
        default=0.0,
        help="Hours after the business day start during which checkout "
        "incurs no late charge.",
    )
    floor_ids = fields.One2many("hotel.floor", "property_id", string="Floors")
    room_ids = fields.One2many("hotel.room", "property_id", string="Rooms")
    room_count = fields.Integer(compute="_compute_room_count")
    sellable_room_count = fields.Integer(
        compute="_compute_room_count",
        help="Rooms available for sale: excludes out-of-order and "
        "admin-use rooms. Denominator for occupancy-based pricing.",
    )

    _sql_constraints = [
        (
            "code_company_uniq",
            "unique(code, company_id)",
            "Property code must be unique per company.",
        ),
    ]

    @api.depends("room_ids.active", "room_ids.is_sellable")
    def _compute_room_count(self):
        for prop in self:
            rooms = prop.room_ids.filtered("active")
            prop.room_count = len(rooms)
            prop.sellable_room_count = len(rooms.filtered("is_sellable"))
