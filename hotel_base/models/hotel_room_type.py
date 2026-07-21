from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelRoomType(models.Model):
    _name = "hotel.room.type"
    _description = "Room Type"
    _inherit = ["mail.thread"]
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True, tracking=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    retired_at = fields.Datetime(readonly=True, copy=False, tracking=True)
    retirement_reason = fields.Text(copy=False, tracking=True)
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
    capacity_teenagers = fields.Integer(default=0)
    capacity_children = fields.Integer(default=0)
    capacity_infants = fields.Integer(default=0)
    base_adults = fields.Integer(default=1)
    base_teenagers = fields.Integer(default=0)
    base_children = fields.Integer(default=0)
    base_infants = fields.Integer(default=0)
    max_occupancy = fields.Integer(compute="_compute_max_occupancy", store=True)
    amenity_ids = fields.Many2many("hotel.amenity", string="Amenities")
    room_ids = fields.One2many("hotel.room", "room_type_id", string="Rooms")
    room_count = fields.Integer(compute="_compute_room_count")
    description = fields.Html(translate=True)
    website_description = fields.Html(translate=True)
    room_policy = fields.Html(translate=True)
    website_published = fields.Boolean(default=False)
    website_image = fields.Image(max_width=1920, max_height=1080)
    gallery_attachment_ids = fields.Many2many(
        "ir.attachment",
        "hotel_room_type_attachment_rel",
        "room_type_id",
        "attachment_id",
        string="Website Gallery",
    )

    @api.depends("room_ids.active")
    def _compute_room_count(self):
        for rtype in self:
            rtype.room_count = len(rtype.room_ids.filtered("active"))

    @api.depends(
        "capacity_adults",
        "capacity_teenagers",
        "capacity_children",
        "capacity_infants",
    )
    def _compute_max_occupancy(self):
        for room_type in self:
            room_type.max_occupancy = (
                room_type.capacity_adults
                + room_type.capacity_teenagers
                + room_type.capacity_children
                + room_type.capacity_infants
            )

    @api.constrains(
        "capacity_adults",
        "capacity_teenagers",
        "capacity_children",
        "capacity_infants",
        "base_adults",
        "base_teenagers",
        "base_children",
        "base_infants",
    )
    def _check_occupancy_limits(self):
        for room_type in self:
            values = [
                room_type.capacity_adults,
                room_type.capacity_teenagers,
                room_type.capacity_children,
                room_type.capacity_infants,
                room_type.base_adults,
                room_type.base_teenagers,
                room_type.base_children,
                room_type.base_infants,
            ]
            if min(values) < 0:
                raise ValidationError(_("Room occupancy values cannot be negative."))
            if (
                room_type.base_adults > room_type.capacity_adults
                or room_type.base_teenagers > room_type.capacity_teenagers
                or room_type.base_children > room_type.capacity_children
                or room_type.base_infants > room_type.capacity_infants
            ):
                raise ValidationError(
                    _("Base occupancy cannot exceed the room type capacity.")
                )

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
                    "sale_ok": False,
                    "purchase_ok": False,
                    "company_id": (rtype.property_id.company_id or self.env.company).id,
                }
            )
        room_types._secure_website_gallery()
        return room_types

    def write(self, vals):
        if vals.get("active") is False and self.mapped("room_ids").filtered("active"):
            raise UserError(
                _("Retire or reassign all active rooms before retiring a room type.")
            )
        if "active" in vals:
            vals = dict(vals)
            vals["retired_at"] = False if vals["active"] else fields.Datetime.now()
            if vals["active"]:
                vals["retirement_reason"] = False
        res = super().write(vals)
        if "base_price" in vals:
            for rtype in self.filtered("product_id"):
                rtype.product_id.list_price = rtype.base_price
        if "active" in vals:
            for rtype in self.filtered("product_id"):
                rtype.product_id.active = bool(vals["active"])
        if "gallery_attachment_ids" in vals:
            self._secure_website_gallery()
        return res

    def _secure_website_gallery(self):
        attachments = self.mapped("gallery_attachment_ids")
        if attachments:
            attachments.sudo().write({"public": False})
        return True

    @api.constrains("gallery_attachment_ids")
    def _check_website_gallery_images(self):
        for room_type in self:
            invalid = room_type.gallery_attachment_ids.filtered(
                lambda attachment: not (attachment.mimetype or "").startswith("image/")
            )
            if invalid:
                raise ValidationError(_("Room-type website galleries accept images only."))

    @api.constrains("property_id", "product_id")
    def _check_rate_product_company(self):
        for room_type in self.filtered("product_id"):
            product_company = room_type.product_id.company_id
            property_company = room_type.property_id.company_id
            if product_company and property_company and product_company != property_company:
                raise ValidationError(
                    _("The room-rate product must belong to the room type company.")
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise UserError(_("Room types cannot be deleted. Archive unused room types instead."))
