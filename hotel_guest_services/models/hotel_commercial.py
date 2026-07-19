import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelService(models.Model):
    _name = "hotel.service"
    _description = "Hotel Guest Service"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, translate=True, tracking=True)
    active = fields.Boolean(default=True)
    website_published = fields.Boolean(
        string="Published on Website",
        default=False,
        help="Show this service on the public hotel website and booking basket.",
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    product_id = fields.Many2one(
        "product.product",
        domain=[("type", "=", "service")],
        ondelete="restrict",
        copy=False,
    )
    charge_policy = fields.Selection(
        [("paid", "Paid"), ("free", "Free")], default="paid", required=True
    )
    is_paid = fields.Boolean(compute="_compute_is_paid", store=True)
    is_meal = fields.Boolean(string="Meal / Kitchen Item")
    default_price = fields.Monetary(currency_field="currency_id", default=0.0)
    currency_id = fields.Many2one(
        "res.currency", related="property_id.company_id.currency_id", readonly=True
    )
    image = fields.Image(max_width=1024, max_height=1024)
    tax_ids = fields.Many2many(
        related="product_id.taxes_id", string="Customer Taxes", readonly=False
    )

    @api.depends("charge_policy")
    def _compute_is_paid(self):
        for service in self:
            service.is_paid = service.charge_policy == "paid"

    @api.model_create_multi
    def create(self, vals_list):
        services = super().create(vals_list)
        for service in services.filtered(lambda item: not item.product_id):
            service.product_id = self.env["product.product"].with_company(
                service.property_id.company_id
            ).create(
                {
                    "name": service.name,
                    "type": "service",
                    "list_price": service.default_price,
                    "sale_ok": False,
                    "purchase_ok": False,
                    "company_id": service.property_id.company_id.id,
                }
            )
        return services

    def write(self, vals):
        result = super().write(vals)
        if "default_price" in vals:
            for service in self.filtered("product_id"):
                service.product_id.list_price = service.default_price
        if "active" in vals:
            for service in self.filtered("product_id"):
                service.product_id.active = bool(vals["active"])
        return result

    @api.constrains("property_id", "product_id")
    def _check_service_product_company(self):
        for service in self.filtered("product_id"):
            product_company = service.product_id.company_id
            if product_company and product_company != service.property_id.company_id:
                raise ValidationError(
                    _("The hotel service product must belong to the hotel company.")
                )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise UserError(_("Hotel services cannot be deleted. Archive them instead."))


class HotelRoomType(models.Model):
    _inherit = "hotel.room.type"

    complimentary_service_ids = fields.Many2many(
        "hotel.service",
        "hotel_room_type_complimentary_service_rel",
        "room_type_id",
        "service_id",
        string="Complimentary Services",
    )
    optional_service_ids = fields.Many2many(
        "hotel.service",
        "hotel_room_type_optional_service_rel",
        "room_type_id",
        "service_id",
        string="Optional Services",
    )

    @api.constrains("property_id", "complimentary_service_ids", "optional_service_ids")
    def _check_hotel_service_scope(self):
        for room_type in self:
            foreign_services = (
                room_type.complimentary_service_ids | room_type.optional_service_ids
            ).filtered(lambda service: service.property_id != room_type.property_id)
            if foreign_services:
                raise ValidationError(
                    _("Room-type services must belong to the same hotel.")
                )


class HotelReservationService(models.Model):
    _name = "hotel.reservation.service"
    _description = "Allotted Hotel Service"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "service_date, id"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    reservation_id = fields.Many2one(
        "hotel.reservation", required=True, ondelete="restrict", index=True, tracking=True
    )
    property_id = fields.Many2one(
        related="reservation_id.property_id", store=True, readonly=True
    )
    room_id = fields.Many2one(related="reservation_id.room_id", store=True, readonly=True)
    service_id = fields.Many2one("hotel.service", required=True, ondelete="restrict")
    product_id = fields.Many2one(related="service_id.product_id", readonly=True)
    service_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    assigned_user_id = fields.Many2one("res.users", string="Assigned To", tracking=True)
    is_meal = fields.Boolean(related="service_id.is_meal", store=True)
    complimentary = fields.Boolean(default=False, tracking=True)
    quantity = fields.Float(default=1.0, required=True)
    unit_price = fields.Monetary(currency_field="currency_id", required=True)
    amount_total = fields.Monetary(
        currency_field="currency_id", compute="_compute_amount_total", store=True
    )
    currency_id = fields.Many2one(related="reservation_id.currency_id", readonly=True)
    notes = fields.Text()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("done", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
    )
    folio_line_id = fields.Many2one("hotel.folio.line", readonly=True, copy=False)

    _quantity_check = models.Constraint(
        "CHECK (quantity > 0)", "Service quantity must be greater than zero."
    )
    _price_check = models.Constraint(
        "CHECK (unit_price >= 0)", "Service price cannot be negative."
    )

    @api.depends("quantity", "unit_price", "complimentary")
    def _compute_amount_total(self):
        for line in self:
            line.amount_total = 0.0 if line.complimentary else line.quantity * line.unit_price

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hotel.reservation.service"
                ) or _("New")
            service = self.env["hotel.service"].browse(vals.get("service_id"))
            if service:
                vals.setdefault("unit_price", service.default_price)
                vals.setdefault("complimentary", service.charge_policy == "free")
        return super().create(vals_list)

    def _write_state(self, state, **extra):
        return super(HotelReservationService, self).write({"state": state, **extra})

    def action_confirm(self):
        for line in self:
            if line.state != "draft":
                raise UserError(_("Only draft hotel services can be confirmed."))
            line._write_state("confirmed")
        return True

    def action_done(self):
        for line in self:
            if line.state != "confirmed":
                raise UserError(_("Only confirmed hotel services can be completed."))
            folio_line = self.env["hotel.folio.line"]
            if not line.complimentary and line.amount_total:
                folio = line.reservation_id.folio_ids[:1]
                if not folio:
                    raise UserError(_("Confirm the reservation before posting a paid service."))
                folio_line = folio._add_workflow_charge(
                    line.product_id,
                    qty=line.quantity,
                    price_unit=line.unit_price,
                    date=line.service_date,
                    source_type="service",
                    source_reference=line.name,
                    source_key=f"reservation_service:{line.id}",
                )
            line._write_state("done", folio_line_id=folio_line.id)
        return True

    def action_cancel(self):
        for line in self:
            if line.state == "done":
                raise UserError(_("Completed services must be reversed from their folio charge."))
            line._write_state("cancelled")
        return True

    def write(self, vals):
        if "state" in vals and any(line.state != vals["state"] for line in self):
            raise UserError(_("Hotel service status is controlled by workflow actions."))
        if self.filtered(lambda line: line.state in ("done", "cancelled")):
            raise UserError(_("Completed or cancelled hotel services are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda line: line.state != "draft"):
            raise UserError(_("Only draft hotel services can be deleted."))
        return super().unlink()


class HotelDocumentType(models.Model):
    _name = "hotel.document.type"
    _description = "Required Hotel Document Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    required_for_website = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
    notes = fields.Text(translate=True)

    _name_property_unique = models.Constraint(
        "unique (name, property_id)", "Document type names must be unique per hotel."
    )


class HotelReservationDocument(models.Model):
    _name = "hotel.reservation.document"
    _description = "Private Reservation Document"
    _inherit = ["mail.thread"]
    _order = "id desc"

    reservation_id = fields.Many2one(
        "hotel.reservation", required=True, ondelete="cascade", index=True
    )
    property_id = fields.Many2one(
        related="reservation_id.property_id", store=True, readonly=True
    )
    partner_id = fields.Many2one(
        related="reservation_id.partner_id", store=True, readonly=True
    )
    document_type_id = fields.Many2one("hotel.document.type", required=True)
    attachment_id = fields.Many2one("ir.attachment", required=True, ondelete="restrict")
    expiry_date = fields.Date()
    verified = fields.Boolean(readonly=True, tracking=True)
    verified_by_id = fields.Many2one("res.users", readonly=True)
    verified_at = fields.Datetime(readonly=True)
    notes = fields.Text()

    _reservation_document_unique = models.Constraint(
        "unique (reservation_id, partner_id, document_type_id)",
        "Only one document of each type is allowed per guest and reservation.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        documents = super().create(vals_list)
        for document in documents:
            document.attachment_id.sudo().write(
                {"public": False, "res_model": document._name, "res_id": document.id}
            )
        return documents

    def action_verify(self):
        return super(HotelReservationDocument, self).write(
            {
                "verified": True,
                "verified_by_id": self.env.user.id,
                "verified_at": fields.Datetime.now(),
            }
        )

    def action_reset_verification(self):
        if not self.env.user.has_group("hotel_base.group_hotel_manager"):
            raise UserError(_("Only a hotel manager can reset document verification."))
        return super(HotelReservationDocument, self).write(
            {"verified": False, "verified_by_id": False, "verified_at": False}
        )

    def write(self, vals):
        if {"verified", "verified_by_id", "verified_at"}.intersection(vals):
            raise UserError(_("Document verification is controlled by its actions."))
        return super().write(vals)


class HotelGuestRating(models.Model):
    _name = "hotel.guest.rating"
    _description = "Hotel Guest Rating"
    _inherit = ["mail.thread"]
    _order = "submitted_at desc, id desc"

    reservation_id = fields.Many2one(
        "hotel.reservation", required=True, ondelete="restrict", index=True
    )
    property_id = fields.Many2one(
        related="reservation_id.property_id", store=True, readonly=True
    )
    partner_id = fields.Many2one(
        related="reservation_id.partner_id", store=True, readonly=True
    )
    access_token = fields.Char(default=lambda self: secrets.token_urlsafe(32), readonly=True, copy=False)
    rating = fields.Integer(aggregator="avg")
    cleanliness_rating = fields.Integer(aggregator="avg")
    service_rating = fields.Integer(aggregator="avg")
    value_rating = fields.Integer(aggregator="avg")
    comments = fields.Text()
    submitted_at = fields.Datetime(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Awaiting Feedback"),
            ("submitted", "Submitted"),
            ("approved", "Published"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
    )

    _reservation_unique = models.Constraint(
        "unique (reservation_id)", "Only one rating is allowed per completed stay."
    )
    _token_unique = models.Constraint("unique (access_token)", "Rating access tokens must be unique.")

    @api.constrains("rating", "cleanliness_rating", "service_rating", "value_rating")
    def _check_ratings(self):
        for review in self:
            values = [
                review.rating,
                review.cleanliness_rating,
                review.service_rating,
                review.value_rating,
            ]
            if any(value and not 1 <= value <= 5 for value in values):
                raise ValidationError(_("Guest ratings must be between 1 and 5."))

    def _submit_public_feedback(self, values):
        self.ensure_one()
        if self.state != "draft" or self.reservation_id.state != "checked_out":
            raise UserError(_("Feedback is available only once after checkout."))
        allowed = {"rating", "cleanliness_rating", "service_rating", "value_rating", "comments"}
        values = {key: value for key, value in values.items() if key in allowed}
        return super(HotelGuestRating, self).write(
            {**values, "state": "submitted", "submitted_at": fields.Datetime.now()}
        )

    def action_approve(self):
        self.filtered(lambda review: review.state == "submitted")._write_state("approved")
        return True

    def action_reject(self):
        self.filtered(lambda review: review.state == "submitted")._write_state("rejected")
        return True

    def _write_state(self, state):
        return super(HotelGuestRating, self).write({"state": state})

    def write(self, vals):
        if "state" in vals and any(review.state != vals["state"] for review in self):
            raise UserError(_("Rating publication is controlled by its actions."))
        return super().write(vals)


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    service_line_ids = fields.One2many(
        "hotel.reservation.service", "reservation_id", string="Service Orders"
    )
    document_ids = fields.One2many(
        "hotel.reservation.document", "reservation_id", string="Guest Documents"
    )
    rating_ids = fields.One2many(
        "hotel.guest.rating", "reservation_id", string="Guest Rating"
    )

    def action_confirm(self):
        newly_confirmed = self.filtered(
            lambda reservation: reservation.state in ("draft", "pending_payment")
        )
        result = super().action_confirm()
        for reservation in newly_confirmed:
            existing_services = reservation.service_line_ids.mapped("service_id")
            for service in reservation.room_type_id.complimentary_service_ids - existing_services:
                self.env["hotel.reservation.service"].create(
                    {
                        "reservation_id": reservation.id,
                        "service_id": service.id,
                        "service_date": reservation.checkin_date,
                        "complimentary": True,
                    }
                ).action_confirm()
        return result

    def action_check_out(self):
        result = super().action_check_out()
        for reservation in self:
            if not reservation.rating_ids:
                self.env["hotel.guest.rating"].create({"reservation_id": reservation.id})
        return result


class HotelFolioLine(models.Model):
    _inherit = "hotel.folio.line"

    source_type = fields.Selection(
        selection_add=[("service", "Hotel Service")],
        ondelete={"service": "set default"},
    )
