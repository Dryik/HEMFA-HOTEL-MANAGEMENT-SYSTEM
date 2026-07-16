from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    booking_source_config_id = fields.Many2one(
        "hotel.booking.source",
        string="Booking Source Pricing",
        domain="[('property_id', '=', property_id), ('source', '=', booking_source), ('active', '=', True)]",
        tracking=True,
    )
    rate_line_ids = fields.One2many(
        "hotel.reservation.rate.line", "reservation_id", string="Nightly Rates"
    )

    rate_locked = fields.Boolean(
        string="Rate Locked",
        default=False,
        tracking=True,
        help="If checked, nightly rate will not be updated automatically by seasonal pricing or occupancy bands.",
    )

    @api.onchange("property_id", "booking_source")
    def _onchange_booking_source_pricelist(self):
        for reservation in self:
            source = self.env["hotel.booking.source"].search(
                [
                    ("property_id", "=", reservation.property_id.id),
                    ("source", "=", reservation.booking_source),
                    ("active", "=", True),
                ],
                limit=1,
            )
            reservation.booking_source_config_id = source
            if source:
                reservation.pricelist_id = source.pricelist_id

    @api.onchange("partner_id")
    def _onchange_partner_hotel_pricelist(self):
        for reservation in self.filtered("partner_id"):
            partner = reservation.partner_id.with_company(
                reservation.property_id.company_id or self.env.company
            )
            if partner.specific_property_product_pricelist:
                reservation.pricelist_id = partner.specific_property_product_pricelist

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            property_id = values.get("property_id") or self.env[
                "hotel.property"
            ]._get_default_property().id
            source = self.env["hotel.booking.source"].search(
                [
                    ("property_id", "=", property_id),
                    ("source", "=", values.get("booking_source", "direct")),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if source and not values.get("booking_source_config_id"):
                values["booking_source_config_id"] = source.id
            if not values.get("pricelist_id"):
                company = source.company_id or self.env["hotel.property"].browse(
                    property_id
                ).company_id
                partner = self.env["res.partner"].browse(
                    values.get("partner_id")
                ).exists().with_company(company)
                explicit_pricelist = partner.specific_property_product_pricelist
                fallback_pricelist = partner.property_product_pricelist
                values["pricelist_id"] = (
                    explicit_pricelist or source.pricelist_id or fallback_pricelist
                ).id
        return super().create(vals_list)

    @api.depends(
        "room_type_id",
        "room_id",
        "checkin_date",
        "checkout_date",
        "partner_id",
        "pricelist_id",
        "adults",
        "teenagers",
        "children",
        "infants",
        "rate_locked",
    )
    def _compute_rate_night(self):
        locked_recs = self.filtered("rate_locked")
        for rec in locked_recs:
            if not rec.rate_night:
                super(HotelReservation, rec)._compute_rate_night()
        for rec in self - locked_recs:
            rtype = rec.room_type_id or rec.room_id.room_type_id
            if not rtype or not rec.property_id or not rec.checkin_date or not rec.checkout_date:
                rec.rate_night = 0.0
                continue
            quote = self.env["hotel.rate.quote"].quote(
                rec.property_id.id,
                rtype.id,
                rec.checkin_date,
                rec.checkout_date,
                partner_id=rec.partner_id.id,
                pricelist_id=rec.pricelist_id.id,
                adults=rec.adults,
                teenagers=rec.teenagers,
                children=rec.children,
                infants=rec.infants,
                exclude_reservation_id=rec.id if isinstance(rec.id, int) else None,
            )
            rec.rate_night = (
                quote["amount_untaxed"] / len(quote["nights"])
                if quote["nights"]
                else 0.0
            )

    @api.depends("rate_night", "nights", "rate_line_ids.amount_untaxed")
    def _compute_amount_total(self):
        with_lines = self.filtered("rate_line_ids")
        for reservation in with_lines:
            reservation.amount_total = sum(
                reservation.rate_line_ids.mapped("amount_untaxed")
            )
        super(HotelReservation, self - with_lines)._compute_amount_total()

    def _refresh_rate_lines(self):
        for reservation in self:
            if reservation.rate_locked:
                raise UserError(_("Confirmed nightly rates cannot be regenerated."))
            room_type = reservation.room_type_id or reservation.room_id.room_type_id
            quote = self.env["hotel.rate.quote"].quote(
                reservation.property_id.id,
                room_type.id,
                reservation.checkin_date,
                reservation.checkout_date,
                partner_id=reservation.partner_id.id,
                pricelist_id=reservation.pricelist_id.id,
                adults=reservation.adults,
                teenagers=reservation.teenagers,
                children=reservation.children,
                infants=reservation.infants,
                exclude_reservation_id=reservation.id,
            )
            reservation.rate_line_ids.unlink()
            for values in quote["nights"]:
                values = dict(values)
                values.update(
                    {
                        "reservation_id": reservation.id,
                        "tax_ids": [(6, 0, values.pop("tax_ids"))],
                    }
                )
                self.env["hotel.reservation.rate.line"].create(values)
            average = (
                quote["amount_untaxed"] / len(quote["nights"])
                if quote["nights"]
                else 0.0
            )
            reservation._write_quote_values(
                {"rate_night": average, "currency_id": quote["currency_id"]}
            )
        return True

    def action_confirm(self):
        preserve_snapshot = self.env.context.get("hotel_preserve_rate_snapshot")
        to_refresh = self.filtered(
            lambda reservation: not reservation.rate_locked
            and not (preserve_snapshot and reservation.rate_line_ids)
        )
        to_refresh._refresh_rate_lines()
        super().action_confirm()
        self._set_confirmed_rate_lock()

    def _set_confirmed_rate_lock(self):
        return super(HotelReservation, self).write({"rate_locked": True})

    def write(self, vals):
        if "booking_source_config_id" in vals and self.filtered(
            lambda reservation: reservation.state != "draft"
        ):
            raise UserError(_("Confirmed booking-source pricing cannot be changed."))
        if "rate_locked" in vals and not (
            self.env.su and self.env.context.get("hotel_migration")
        ):
            raise UserError(_("Confirmed-rate locking is controlled by hotel workflows."))
        return super().write(vals)


class HotelReservationAmendment(models.Model):
    _inherit = "hotel.reservation.amendment"

    def _apply_financial_effects(self, before, after):
        self.ensure_one()
        self._reverse_and_regenerate_future_rates()
        self.reservation_id.invalidate_recordset(["amount_total"])
        after["amount_total"] = self.reservation_id.amount_total
        return super()._apply_financial_effects(before, after)

    def _reverse_and_regenerate_future_rates(self):
        self.ensure_one()
        reservation = self.reservation_id
        effective_business_date = reservation.property_id.get_business_date(
            self.effective_date
        )
        old_lines = reservation.rate_line_ids.filtered(
            lambda line: not line.superseded
            and not line.reversal_of_id
            and line.business_date >= effective_business_date
        )
        line_model = self.env["hotel.reservation.rate.line"]
        old_posted_by_date = {line.business_date: line.posted for line in old_lines}
        for line in old_lines:
            line._supersede(self)
            line_model.create(
                {
                    "reservation_id": reservation.id,
                    "business_date": line.business_date,
                    "currency_id": line.currency_id.id,
                    "base_amount": -line.base_amount,
                    "hotel_rate_rule_id": line.hotel_rate_rule_id.id,
                    "occupancy_band_id": line.occupancy_band_id.id,
                    "occupancy_multiplier": line.occupancy_multiplier,
                    "pricelist_item_id": line.pricelist_item_id.id,
                    "fiscal_position_id": line.fiscal_position_id.id,
                    "room_amount": -line.room_amount,
                    "supplement_amount": -line.supplement_amount,
                    "supplement_trace": line.supplement_trace,
                    "tax_amount": -line.tax_amount,
                    "amount_untaxed": -line.amount_untaxed,
                    "amount_total": -line.amount_total,
                    "tax_ids": [(6, 0, line.tax_ids.ids)],
                    "posted": line.posted,
                    "amendment_id": self.id,
                    "reversal_of_id": line.id,
                }
            )
        room_type = reservation.room_type_id or reservation.room_id.room_type_id
        quote = self.env["hotel.rate.quote"].quote(
            reservation.property_id.id,
            room_type.id,
            reservation.checkin_date,
            reservation.checkout_date,
            partner_id=reservation.partner_id.id,
            pricelist_id=reservation.pricelist_id.id,
            adults=reservation.adults,
            teenagers=reservation.teenagers,
            children=reservation.children,
            infants=reservation.infants,
            exclude_reservation_id=reservation.id,
        )
        for values in quote["nights"]:
            if values["business_date"] < effective_business_date:
                continue
            values = dict(values)
            if self.amendment_type == "reprice":
                old_untaxed = values["amount_untaxed"]
                values["base_amount"] = self.new_rate_night
                values["room_amount"] = self.new_rate_night
                values["amount_untaxed"] = self.new_rate_night + values["supplement_amount"]
                if old_untaxed:
                    tax_ratio = values["tax_amount"] / old_untaxed
                    values["tax_amount"] = values["amount_untaxed"] * tax_ratio
                values["amount_total"] = values["amount_untaxed"] + values["tax_amount"]
            posted = (
                reservation.property_id.stay_charge_policy == "entire_stay"
                or old_posted_by_date.get(values["business_date"], False)
            )
            values.update(
                {
                    "reservation_id": reservation.id,
                    "tax_ids": [(6, 0, values.pop("tax_ids"))],
                    "posted": posted,
                    "amendment_id": self.id,
                }
            )
            line_model.create(values)
        return True
