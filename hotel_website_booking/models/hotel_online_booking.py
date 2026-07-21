import uuid
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


ONLINE_BOOKING_STATES = [
    ("draft", "Draft"),
    ("pending_review", "Pending Review"),
    ("held", "Held"),
    ("payment_pending", "Payment Pending"),
    ("confirmed", "Confirmed"),
    ("expired", "Expired"),
    ("cancelled", "Cancelled"),
    ("payment_exception", "Payment Exception"),
]


class HotelOnlineBooking(models.Model):
    _name = "hotel.online.booking"
    _description = "Sales-free Hotel Online Booking"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), readonly=True, copy=False)
    access_token = fields.Char(
        default=lambda self: uuid.uuid4().hex,
        required=True,
        readonly=True,
        copy=False,
        index=True,
        groups="hotel_base.group_hotel_frontdesk",
    )
    website_id = fields.Many2one("website", required=True, ondelete="restrict")
    property_id = fields.Many2one("hotel.property", required=True, ondelete="restrict")
    company_id = fields.Many2one(
        related="property_id.company_id", store=True, readonly=True, index=True
    )
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    checkin_date = fields.Datetime(required=True, tracking=True)
    checkout_date = fields.Datetime(required=True, tracking=True)
    adults = fields.Integer(default=1)
    teenagers = fields.Integer(default=0)
    children = fields.Integer(default=0)
    infants = fields.Integer(default=0)
    nationality_id = fields.Many2one("res.country")
    pricelist_id = fields.Many2one("product.pricelist")
    currency_id = fields.Many2one("res.currency", required=True)
    line_ids = fields.One2many(
        "hotel.online.booking.line", "booking_id", string="Rooms"
    )
    service_line_ids = fields.One2many(
        "hotel.online.booking.service", "booking_id", string="Services"
    )
    quote_snapshot = fields.Json(readonly=True, copy=False)
    amount_untaxed = fields.Monetary(readonly=True, copy=False)
    amount_tax = fields.Monetary(readonly=True, copy=False)
    amount_total = fields.Monetary(readonly=True, copy=False)
    amount_due_online = fields.Monetary(readonly=True, copy=False)
    payment_policy = fields.Selection(
        related="property_id.online_payment_policy", readonly=True
    )
    expires_at = fields.Datetime(readonly=True, copy=False, index=True)
    group_id = fields.Many2one(
        "hotel.reservation.group", readonly=True, copy=False, ondelete="restrict"
    )
    reservation_ids = fields.Many2many(
        "hotel.reservation",
        "hotel_online_booking_reservation_rel",
        "booking_id",
        "reservation_id",
        readonly=True,
        copy=False,
    )
    transaction_ids = fields.One2many(
        "payment.transaction", "hotel_online_booking_id", readonly=True
    )
    allocation_ids = fields.One2many(
        "hotel.payment.allocation", "online_booking_id", readonly=True
    )
    state = fields.Selection(
        ONLINE_BOOKING_STATES,
        default="draft",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
        index=True,
    )
    customer_note = fields.Text()
    exception_note = fields.Text(readonly=True, copy=False)

    _date_check = models.Constraint(
        "CHECK (checkout_date > checkin_date)",
        "Departure must be after arrival.",
    )
    _token_unique = models.Constraint(
        "UNIQUE(access_token)", "Online booking access tokens must be unique."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.online.booking")
                    or _("New")
                )
            property_rec = self.env["hotel.property"].browse(
                values.get("property_id")
            )
            if property_rec and not values.get("currency_id"):
                pricelist = self.env["product.pricelist"].browse(
                    values.get("pricelist_id")
                )
                values["currency_id"] = (
                    pricelist.currency_id or property_rec.company_id.currency_id
                ).id
        return super().create(vals_list)

    @api.constrains(
        "property_id",
        "website_id",
        "partner_id",
        "pricelist_id",
        "adults",
        "teenagers",
        "children",
        "infants",
    )
    def _check_booking_scope(self):
        for booking in self:
            if booking.website_id.company_id != booking.company_id:
                raise ValidationError(_("The website and hotel must use the same company."))
            if booking.property_id.website_id != booking.website_id:
                raise ValidationError(_("The booking website is not assigned to this hotel."))
            if booking.partner_id.company_id and booking.partner_id.company_id != booking.company_id:
                raise ValidationError(_("The guest must belong to the booking company."))
            if booking.pricelist_id.company_id and booking.pricelist_id.company_id != booking.company_id:
                raise ValidationError(_("The pricelist must belong to the booking company."))
            if min(booking.adults, booking.teenagers, booking.children, booking.infants) < 0:
                raise ValidationError(_("Guest counts cannot be negative."))
            if booking.adults < 1:
                raise ValidationError(_("At least one adult is required."))

    def _json_quote(self, quote):
        serialized = dict(quote)
        serialized["nights"] = [
            {
                **line,
                "business_date": fields.Date.to_string(line["business_date"]),
            }
            for line in quote["nights"]
        ]
        return serialized

    def action_reprice(self):
        for booking in self:
            if booking.state not in ("draft", "pending_review"):
                raise UserError(_("Only draft booking requests can be repriced."))
            if not booking.line_ids:
                raise UserError(_("Select at least one room."))
            room_untaxed = room_tax = room_total = 0.0
            quote_lines = []
            for line in booking.line_ids:
                quote = self.env["hotel.rate.quote"].with_company(
                    booking.company_id
                ).quote(
                    booking.property_id.id,
                    line.room_type_id.id,
                    booking.checkin_date,
                    booking.checkout_date,
                    partner_id=booking.partner_id.id,
                    pricelist_id=booking.pricelist_id.id,
                    adults=line.adults or booking.adults,
                    teenagers=line.teenagers or booking.teenagers,
                    children=line.children or booking.children,
                    infants=line.infants or booking.infants,
                )
                snapshot = booking._json_quote(quote)
                line._write_quote_values(
                    {
                        "currency_id": quote["currency_id"],
                        "unit_amount_untaxed": quote["amount_untaxed"],
                        "unit_tax": quote["tax_amount"],
                        "unit_amount_total": quote["amount_total"],
                        "amount_total": quote["amount_total"] * line.quantity,
                        "quote_snapshot": snapshot,
                    }
                )
                room_untaxed += quote["amount_untaxed"] * line.quantity
                room_tax += quote["tax_amount"] * line.quantity
                room_total += quote["amount_total"] * line.quantity
                quote_lines.append({"line_id": line.id, **snapshot})
            service_untaxed = service_tax = service_total = 0.0
            for service_line in booking.service_line_ids:
                values = service_line._get_quote_values(booking)
                service_line._write_quote_values(values)
                service_untaxed += values["amount_untaxed"]
                service_tax += values["amount_tax"]
                service_total += values["amount_total"]
            amount_total = booking.currency_id.round(room_total + service_total)
            amount_due = booking._compute_online_amount(amount_total)
            booking._write_workflow_values(
                {
                    "quote_snapshot": {
                        "quoted_at": fields.Datetime.to_string(fields.Datetime.now()),
                        "rooms": quote_lines,
                        "service_total": service_total,
                    },
                    "amount_untaxed": booking.currency_id.round(
                        room_untaxed + service_untaxed
                    ),
                    "amount_tax": booking.currency_id.round(room_tax + service_tax),
                    "amount_total": amount_total,
                    "amount_due_online": amount_due,
                }
            )
        return True

    def _compute_online_amount(self, total):
        self.ensure_one()
        policy = self.property_id.online_payment_policy
        value = self.property_id.online_deposit_value
        if policy == "fixed_deposit":
            amount = min(value, total)
        elif policy == "percent_deposit":
            amount = total * value / 100.0
        elif policy == "full":
            amount = total
        else:
            amount = 0.0
        return self.currency_id.round(amount)

    def action_submit(self):
        for booking in self:
            if booking.state != "draft":
                raise UserError(_("Only a draft booking can be submitted."))
            booking.action_reprice()
            if (
                booking.property_id.online_payment_policy == "manual"
                or float_is_zero(
                    booking.amount_due_online,
                    precision_rounding=booking.currency_id.rounding,
                )
            ):
                booking._write_workflow_values({"state": "pending_review"})
            else:
                booking._allocate_reservations(hold_for_payment=True)
            booking._send_template("hotel_website_booking.mail_template_booking_request")
        return True

    def _allocate_reservations(self, hold_for_payment):
        self.ensure_one()
        if self.group_id or self.reservation_ids:
            raise UserError(_("Rooms have already been allocated to this booking."))
        assignments = self.env["hotel.availability.service"].assign_rooms(
            self.property_id.id,
            self.checkin_date,
            self.checkout_date,
            [
                {"room_type_id": line.room_type_id.id, "quantity": line.quantity}
                for line in self.line_ids
            ],
            website_only=True,
        )
        group = self.env["hotel.reservation.group"].create(
            {
                "property_id": self.property_id.id,
                "group_partner_id": self.partner_id.id,
                "billing_partner_id": self.partner_id.id,
                "checkin_date": self.checkin_date,
                "checkout_date": self.checkout_date,
                "allocation_line_ids": [
                    Command.create(
                        {
                            "room_type_id": line.room_type_id.id,
                            "requested_qty": line.quantity,
                        }
                    )
                    for line in self.line_ids
                ],
            }
        )
        line_by_type = {line.room_type_id.id: line for line in self.line_ids}
        reservations = self.env["hotel.reservation"]
        for assignment in assignments:
            line = line_by_type[assignment["room_type_id"]]
            reservations |= self.env["hotel.reservation"].create(
                {
                    "partner_id": self.partner_id.id,
                    "property_id": self.property_id.id,
                    "room_type_id": assignment["room_type_id"],
                    "room_id": assignment["room_id"],
                    "checkin_date": self.checkin_date,
                    "checkout_date": self.checkout_date,
                    "group_id": group.id,
                    "booking_source": "website",
                    "responsible_id": False,
                    "pricelist_id": self.pricelist_id.id,
                    "adults": line.adults or self.adults,
                    "teenagers": line.teenagers or self.teenagers,
                    "children": line.children or self.children,
                    "infants": line.infants or self.infants,
                    "currency_id": self.currency_id.id,
                }
            )
        self._write_workflow_values(
            {
                "group_id": group.id,
                "reservation_ids": [Command.set(reservations.ids)],
            }
        )
        if hold_for_payment:
            # Capture one immutable nightly snapshot before the newly held rooms
            # themselves affect occupancy-based pricing.
            reservations._refresh_rate_lines()
            expires_at = fields.Datetime.now() + timedelta(
                minutes=self.property_id.online_hold_minutes
            )
            reservations._action_hold_for_payment(expires_at)
            self._write_workflow_values(
                {
                    "state": "payment_pending",
                    "expires_at": expires_at,
                }
            )
        else:
            reservations.with_context(hotel_preserve_rate_snapshot=True).action_confirm()
            group._write_group_state("confirmed")
            self._write_workflow_values({"state": "confirmed", "expires_at": False})
            self._complete_confirmed_services()
            self._send_template("hotel_website_booking.mail_template_booking_confirmation")
        return reservations

    def action_approve_manual(self):
        for booking in self:
            if booking.state != "pending_review":
                raise UserError(_("Only pending booking requests can be approved."))
            booking.action_reprice()
            booking._allocate_reservations(hold_for_payment=False)
        return True

    def _lock(self):
        self.ensure_one()
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (7720, self.id))
        self.invalidate_recordset(["state", "expires_at"])

    def _confirm_paid_transaction(self, transaction):
        self.ensure_one()
        transaction.ensure_one()
        if (
            transaction.state != "done"
            or transaction.hotel_online_booking_id != self
        ):
            raise ValidationError(
                _("Only a successful transaction linked to this booking can confirm it.")
            )
        self._lock()
        if self.state == "confirmed":
            return True
        if self.state == "payment_exception":
            return False
        if self.state not in ("held", "payment_pending"):
            self._set_payment_exception(
                _(
                    "Payment %(reference)s succeeded after the room hold was no longer valid.",
                    reference=transaction.reference,
                )
            )
            return False
        if self.expires_at and self.expires_at < fields.Datetime.now():
            self._expire_hold(payment_exception=True)
            return False
        if (
            transaction.currency_id != self.currency_id
            or float_compare(
                transaction.amount,
                self.amount_due_online,
                precision_rounding=self.currency_id.rounding,
            ) != 0
        ):
            self._set_payment_exception(
                _("The successful transaction amount or currency is invalid.")
            )
            return False
        held = self.reservation_ids.filtered(lambda reservation: reservation.state == "pending_payment")
        held.with_context(hotel_preserve_rate_snapshot=True).action_confirm()
        if self.group_id.state == "draft":
            self.group_id._write_group_state("confirmed")
        self._write_workflow_values(
            {"state": "confirmed", "expires_at": False, "exception_note": False}
        )
        self._complete_confirmed_services()
        self._allocate_payment(transaction.payment_id)
        self._send_template("hotel_website_booking.mail_template_payment_receipt")
        self._send_template("hotel_website_booking.mail_template_booking_confirmation")
        return True

    def _set_payment_exception(self, note, clear_expiry=False):
        self.ensure_one()
        values = {"state": "payment_exception", "exception_note": note}
        if clear_expiry:
            values["expires_at"] = False
        self._write_workflow_values(
            values
        )
        manager_group = self.env.ref(
            "hotel_base.group_hotel_manager", raise_if_not_found=False
        )
        manager = (
            manager_group.user_ids.filtered(
                lambda user: user.active and self.company_id in user.company_ids
            )[:1]
            if manager_group
            else self.env["res.users"]
        )
        self.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=(manager or self.env.user).id,
            summary=_("Review hotel payment exception"),
            note=note,
        )
        return True

    def _allocate_payment(self, payment):
        self.ensure_one()
        if not payment or self.allocation_ids.filtered(lambda item: item.payment_id == payment):
            return False
        folios = self.reservation_ids.mapped("folio_ids")
        if not folios:
            return False
        bases = [max(folio.amount_total, 0.0) for folio in folios]
        base_total = sum(bases)
        remaining = payment.amount
        allocations = self.env["hotel.payment.allocation"]
        for index, folio in enumerate(folios):
            if index == len(folios) - 1:
                amount = remaining
            elif base_total:
                amount = self.currency_id.round(payment.amount * bases[index] / base_total)
            else:
                amount = self.currency_id.round(payment.amount / len(folios))
            remaining -= amount
            allocations |= self.env["hotel.payment.allocation"].create(
                {
                    "online_booking_id": self.id,
                    "payment_id": payment.id,
                    "folio_id": folio.id,
                    "amount": amount,
                    "currency_id": self.currency_id.id,
                }
            )
        allocations._reconcile_posted_documents()
        return True

    def _complete_confirmed_services(self):
        self.ensure_one()
        if not self.service_line_ids or not self.reservation_ids:
            return False
        primary = self.reservation_ids[:1]
        for line in self.service_line_ids:
            self.env["hotel.reservation.service"].create(
                {
                    "reservation_id": primary.id,
                    "room_id": primary.room_id.id,
                    "service_id": line.service_id.id,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "service_date": self.checkin_date,
                }
            ).action_confirm()
        return True

    def _expire_hold(self, payment_exception=False):
        self.ensure_one()
        self._lock()
        held = self.reservation_ids.filtered(lambda reservation: reservation.state == "pending_payment")
        held._action_expire_payment_hold()
        if self.group_id and self.group_id.state == "draft":
            self.group_id._write_group_state("cancelled")
        values = {"expires_at": False}
        if payment_exception:
            self._set_payment_exception(
                _(
                    "Payment arrived after the inventory hold expired. Staff must rebook or refund it."
                ),
                clear_expiry=True,
            )
            return True
        else:
            values["state"] = "expired"
        self._write_workflow_values(values)
        return True

    @api.model
    def _cron_expire_holds(self):
        expired = self.search(
            [
                ("state", "in", ("held", "payment_pending")),
                ("expires_at", "<=", fields.Datetime.now()),
            ]
        )
        for booking in expired:
            booking._expire_hold()
        return True

    def action_cancel_online(self):
        for booking in self:
            if booking.state not in (
                "pending_review",
                "held",
                "payment_pending",
                "payment_exception",
                "confirmed",
            ):
                raise UserError(_("This booking can no longer be cancelled online."))
            if booking.checkin_date <= fields.Datetime.now():
                raise UserError(_("Contact the hotel to cancel after the arrival time."))
            if booking.state in ("held", "payment_pending"):
                booking._expire_hold()
            elif booking.state == "payment_exception":
                booking._release_exception_holds()
                booking._write_workflow_values({"state": "cancelled", "expires_at": False})
            else:
                if booking.group_id and booking.group_id.state == "confirmed":
                    booking.group_id.action_cancel()
                booking._write_workflow_values({"state": "cancelled", "expires_at": False})
            booking._send_template("hotel_website_booking.mail_template_booking_cancellation")
        return True

    def _release_exception_holds(self):
        """Release inventory still held by a booking stuck in payment exception."""
        self.ensure_one()
        self._lock()
        held = self.reservation_ids.filtered(
            lambda reservation: reservation.state == "pending_payment"
        )
        held._action_expire_payment_hold()
        if self.group_id and self.group_id.state == "draft":
            self.group_id._write_group_state("cancelled")
        return True

    def action_return_to_review(self):
        """Staff recovery path: send an exception booking back to the review queue."""
        for booking in self:
            if booking.state != "payment_exception":
                raise UserError(
                    _("Only bookings in payment exception can be returned to review.")
                )
            booking._release_exception_holds()
            booking._write_workflow_values(
                {"state": "pending_review", "expires_at": False, "exception_note": False}
            )
            booking.message_post(
                body=_(
                    "Payment exception returned to review by %(user)s. Previous exception: %(note)s",
                    user=self.env.user.name,
                    note=booking.exception_note or "-",
                )
            )
        return True

    def _send_template(self, xmlid):
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if template and self.partner_id.email:
            template.sudo().send_mail(self.id, force_send=False)

    def _write_workflow_values(self, values):
        return super(HotelOnlineBooking, self).write(values)

    def write(self, values):
        protected = {
            "name",
            "access_token",
            "quote_snapshot",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
            "amount_due_online",
            "expires_at",
            "group_id",
            "reservation_ids",
            "state",
            "exception_note",
        }
        if protected.intersection(values):
            raise UserError(_("Online booking workflow fields cannot be edited directly."))
        if self.filtered(lambda booking: booking.state not in ("draft", "pending_review")):
            editable = {"customer_note"}
            if set(values) - editable:
                raise UserError(_("Allocated online bookings are immutable."))
        return super().write(values)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_unsubmitted(self):
        if self.filtered(lambda booking: booking.state != "draft"):
            raise UserError(_("Submitted online bookings cannot be deleted."))


class HotelOnlineBookingLine(models.Model):
    _name = "hotel.online.booking.line"
    _description = "Hotel Online Booking Room"
    _order = "id"

    booking_id = fields.Many2one(
        "hotel.online.booking", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="booking_id.company_id", store=True)
    room_type_id = fields.Many2one("hotel.room.type", required=True, ondelete="restrict")
    quantity = fields.Integer(default=1, required=True)
    adults = fields.Integer(default=1)
    teenagers = fields.Integer(default=0)
    children = fields.Integer(default=0)
    infants = fields.Integer(default=0)
    currency_id = fields.Many2one("res.currency", readonly=True)
    unit_amount_untaxed = fields.Monetary(readonly=True)
    unit_tax = fields.Monetary(readonly=True)
    unit_amount_total = fields.Monetary(readonly=True)
    amount_total = fields.Monetary(readonly=True)
    quote_snapshot = fields.Json(readonly=True)

    _booking_room_type_unique = models.Constraint(
        "UNIQUE(booking_id, room_type_id)",
        "Each room type can appear only once in an online basket.",
    )
    _quantity_positive = models.Constraint(
        "CHECK(quantity > 0)", "Room quantity must be positive."
    )

    @api.constrains("room_type_id", "booking_id", "adults", "teenagers", "children", "infants")
    def _check_room_line(self):
        for line in self:
            if line.room_type_id.property_id != line.booking_id.property_id:
                raise ValidationError(_("The room type does not belong to this hotel."))
            if not line.room_type_id.active or not line.room_type_id.website_published:
                raise ValidationError(
                    _("The room type is not published for this hotel website.")
                )
            counts = (line.adults, line.teenagers, line.children, line.infants)
            if min(counts) < 0 or line.adults < 1:
                raise ValidationError(_("Every room needs at least one adult and valid guest counts."))
            if (
                line.adults > line.room_type_id.capacity_adults
                or line.teenagers > line.room_type_id.capacity_teenagers
                or line.children > line.room_type_id.capacity_children
                or line.infants > line.room_type_id.capacity_infants
            ):
                raise ValidationError(_("Guest counts exceed the room type capacity."))

    def _write_quote_values(self, values):
        return super(HotelOnlineBookingLine, self).write(values)

    def write(self, values):
        if self.mapped("booking_id").filtered(lambda booking: booking.state != "draft"):
            raise UserError(_("Only draft basket lines can be changed."))
        protected = {
            "currency_id",
            "unit_amount_untaxed",
            "unit_tax",
            "unit_amount_total",
            "amount_total",
            "quote_snapshot",
        }
        if protected.intersection(values):
            raise UserError(_("Online room prices are set by the quote service."))
        return super().write(values)

    def unlink(self):
        if self.mapped("booking_id").filtered(lambda booking: booking.state != "draft"):
            raise UserError(_("Only draft basket lines can be deleted."))
        return super().unlink()


class HotelOnlineBookingService(models.Model):
    _name = "hotel.online.booking.service"
    _description = "Hotel Online Booking Service"

    booking_id = fields.Many2one(
        "hotel.online.booking", required=True, ondelete="cascade", index=True
    )
    service_id = fields.Many2one("hotel.service", required=True, ondelete="restrict")
    quantity = fields.Float(default=1.0, required=True)
    currency_id = fields.Many2one("res.currency", related="booking_id.currency_id")
    unit_price = fields.Monetary(readonly=True)
    amount_untaxed = fields.Monetary(readonly=True)
    amount_tax = fields.Monetary(readonly=True)
    amount_total = fields.Monetary(readonly=True)

    _quantity_positive = models.Constraint(
        "CHECK(quantity > 0)", "Service quantity must be positive."
    )
    _booking_service_unique = models.Constraint(
        "UNIQUE(booking_id, service_id)",
        "Each service can appear only once in an online basket.",
    )

    @api.constrains("booking_id", "service_id")
    def _check_public_service_scope(self):
        for line in self:
            if (
                line.service_id.property_id != line.booking_id.property_id
                or not line.service_id.active
                or not line.service_id.website_published
            ):
                raise ValidationError(
                    _("The selected service is not published for this hotel website.")
                )

    def _get_quote_values(self, booking):
        self.ensure_one()
        unit_price = 0.0
        if self.service_id.is_paid:
            unit_price = self.service_id.currency_id._convert(
                self.service_id.default_price,
                booking.currency_id,
                booking.company_id,
                fields.Date.to_date(booking.checkin_date),
            )
        amount_untaxed = unit_price * self.quantity
        taxes = self.service_id.tax_ids.filtered(
            lambda tax: not tax.company_id or tax.company_id == booking.company_id
        )
        amount_total = amount_untaxed
        if taxes:
            result = taxes.compute_all(
                unit_price,
                booking.currency_id,
                self.quantity,
                product=self.service_id.product_id,
                partner=booking.partner_id,
            )
            amount_untaxed = result["total_excluded"]
            amount_total = result["total_included"]
        return {
            "unit_price": unit_price,
            "amount_untaxed": amount_untaxed,
            "amount_tax": amount_total - amount_untaxed,
            "amount_total": amount_total,
        }

    def _write_quote_values(self, values):
        return super(HotelOnlineBookingService, self).write(values)

    def write(self, values):
        if self.mapped("booking_id").filtered(lambda booking: booking.state != "draft"):
            raise UserError(_("Only draft service selections can be changed."))
        if {"unit_price", "amount_untaxed", "amount_tax", "amount_total"}.intersection(values):
            raise UserError(_("Online service prices are set by the quote service."))
        return super().write(values)

    def unlink(self):
        if self.mapped("booking_id").filtered(lambda booking: booking.state != "draft"):
            raise UserError(_("Only draft service selections can be deleted."))
        return super().unlink()


class HotelPaymentAllocation(models.Model):
    _name = "hotel.payment.allocation"
    _description = "Hotel Group Payment Allocation"
    _order = "id"

    online_booking_id = fields.Many2one(
        "hotel.online.booking", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(related="online_booking_id.company_id", store=True)
    payment_id = fields.Many2one("account.payment", required=True, ondelete="restrict")
    folio_id = fields.Many2one("hotel.folio", required=True, ondelete="restrict")
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one("res.currency", required=True)

    _payment_folio_unique = models.Constraint(
        "UNIQUE(payment_id, folio_id)", "A payment can be allocated to a folio only once."
    )
    _amount_positive = models.Constraint(
        "CHECK(amount >= 0)", "Allocated payment amounts cannot be negative."
    )

    @api.constrains("online_booking_id", "payment_id", "folio_id", "currency_id")
    def _check_allocation_scope(self):
        for allocation in self:
            if allocation.folio_id.reservation_id not in allocation.online_booking_id.reservation_ids:
                raise ValidationError(_("The allocated folio does not belong to the booking."))
            if allocation.payment_id.company_id != allocation.company_id:
                raise ValidationError(_("The payment and booking must use the same company."))
            if allocation.currency_id != allocation.online_booking_id.currency_id:
                raise ValidationError(_("The allocation currency must match the booking currency."))

    def write(self, values):
        raise UserError(_("Payment allocations are immutable."))

    def _reconcile_posted_documents(self):
        """Match posted deposits with posted folio/group invoices when available."""
        for payment in self.mapped("payment_id"):
            allocations = self.filtered(lambda allocation: allocation.payment_id == payment)
            invoices = allocations.mapped("folio_id.invoice_ids")
            invoices |= allocations.mapped("online_booking_id.group_id.invoice_ids")
            invoices = invoices.filtered(
                lambda invoice: invoice.state == "posted"
                and invoice.company_id == payment.company_id
                and invoice.partner_id.commercial_partner_id
                == payment.partner_id.commercial_partner_id
            )
            payment_lines = payment.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
                and not line.reconciled
                and (
                    not line.company_currency_id.is_zero(line.amount_residual)
                    or not line.currency_id.is_zero(line.amount_residual_currency)
                )
            )
            invoice_lines = invoices.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
                and not line.reconciled
                and (
                    not line.company_currency_id.is_zero(line.amount_residual)
                    or not line.currency_id.is_zero(line.amount_residual_currency)
                )
            )
            for account in (payment_lines | invoice_lines).mapped("account_id"):
                lines = (payment_lines | invoice_lines).filtered(
                    lambda line: line.account_id == account
                )
                if (
                    account.reconcile
                    and any(line.balance > 0 for line in lines)
                    and any(line.balance < 0 for line in lines)
                ):
                    lines.reconcile()
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise UserError(_("Payment allocations cannot be deleted."))
