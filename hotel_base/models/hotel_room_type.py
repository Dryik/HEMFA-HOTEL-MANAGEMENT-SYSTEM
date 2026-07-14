from odoo import api, fields, models


class HotelRoomType(models.Model):
    _name = "hotel.room.type"
    _description = "Room Type"
    _inherit = ["mail.thread"]
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True, tracking=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    property_id = fields.Many2one(
        "hotel.property",
        default=lambda self: self.env["hotel.property"]._get_default_property(),
        help="Internal company-to-hotel compatibility link.",
    )
    # Room types are sellable service products so pricing, taxes and
    # accounting reuse the standard product/invoicing machinery.
    product_id = fields.Many2one(
        "product.product",
        string="Rate Product",
        domain=[("type", "=", "service")],
        copy=False,
        help="Service product carrying the base price, taxes and income "
        "account for this room type. Created automatically if empty.",
    )
    base_price = fields.Float(
        string="Base Nightly Price",
        default=0.0,
        tracking=True,
        help="Default nightly rate before seasonal, agency and occupancy "
        "adjustments (hotel_rate).",
    )
    capacity_adults = fields.Integer(default=2)
    capacity_children = fields.Integer(default=0)
    amenity_ids = fields.Many2many("hotel.amenity", string="Amenities")
    room_ids = fields.One2many("hotel.room", "room_type_id", string="Rooms")
    room_count = fields.Integer(compute="_compute_room_count")
    description = fields.Html(translate=True)

    @api.depends("room_ids.active")
    def _compute_room_count(self):
        for rtype in self:
            rtype.room_count = len(rtype.room_ids.filtered("active"))

    @api.model_create_multi
    def create(self, vals_list):
        room_types = super().create(vals_list)
        for rtype in room_types.filtered(lambda r: not r.product_id):
            rtype.product_id = self.env["product.product"].with_company(
                rtype.property_id.company_id or self.env.company
            ).create(
                {
                    "name": rtype.name,
                    "type": "service",
                    "list_price": rtype.base_price,
                    "sale_ok": True,
                    "purchase_ok": False,
                    "company_id": (rtype.property_id.company_id or self.env.company).id,
                }
            )
        return room_types

    def write(self, vals):
        res = super().write(vals)
        if "base_price" in vals:
            for rtype in self.filtered("product_id"):
                rtype.product_id.list_price = rtype.base_price
        return res
