from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


WEEKDAYS = [
    ("0", "Monday"),
    ("1", "Tuesday"),
    ("2", "Wednesday"),
    ("3", "Thursday"),
    ("4", "Friday"),
    ("5", "Saturday"),
    ("6", "Sunday"),
]


class HotelSeasonalPricing(models.Model):
    _name = "hotel.seasonal.pricing"
    _description = "Hotel Seasonal Pricing Plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"

    name = fields.Char(required=True, translate=True, tracking=True)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
        tracking=True,
    )
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    description = fields.Text(translate=True)
    state = fields.Selection(
        [("draft", "Draft"), ("active", "Active"), ("expired", "Expired")],
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
    )
    rate_rule_ids = fields.One2many(
        "hotel.rate.rule", "seasonal_pricing_id", string="Nightly Rate Rules"
    )
    pricelist_item_ids = fields.One2many(
        "product.pricelist.item", "hotel_seasonal_pricing_id", string="Pricelist Rules"
    )

    _date_check = models.Constraint(
        "CHECK (date_end >= date_start)", "The seasonal pricing end date is invalid."
    )

    def action_activate(self):
        for plan in self:
            if plan.state != "draft":
                raise UserError(_("Only draft seasonal plans can be activated."))
            plan._write_state("active")
        return True

    def action_expire(self):
        for plan in self:
            if plan.state != "active":
                raise UserError(_("Only active seasonal plans can be expired."))
            plan._write_state("expired")
        return True

    def _write_state(self, state):
        return super(HotelSeasonalPricing, self).write({"state": state})

    def write(self, vals):
        if "state" in vals and any(plan.state != vals["state"] for plan in self):
            raise UserError(_("Seasonal pricing status is controlled by its actions."))
        if self.filtered(lambda plan: plan.state == "active") and {
            "property_id",
            "date_start",
            "date_end",
        }.intersection(vals):
            raise UserError(_("Expire an active seasonal plan before changing its dates."))
        return super().write(vals)


class HotelRateWeekday(models.Model):
    _name = "hotel.rate.weekday"
    _description = "Hotel Pricing Weekday"
    _order = "code"

    name = fields.Char(required=True, translate=True)
    code = fields.Selection(WEEKDAYS, required=True)

    _code_unique = models.Constraint("unique (code)", "Weekday codes must be unique.")


class HotelGuestSupplement(models.Model):
    _name = "hotel.guest.supplement"
    _description = "Hotel Extra Guest Supplement"
    _order = "room_type_id, guest_category, id"

    name = fields.Char(required=True, translate=True)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    room_type_id = fields.Many2one("hotel.room.type", required=True)
    guest_category = fields.Selection(
        [
            ("adult", "Adult"),
            ("teenager", "Teenager"),
            ("child", "Child"),
            ("infant", "Infant"),
        ],
        required=True,
    )
    charge_type = fields.Selection(
        [("fixed", "Fixed Per Guest / Night"), ("percent", "Percentage of Nightly Rate")],
        default="fixed",
        required=True,
    )
    value = fields.Float(required=True)
    active = fields.Boolean(default=True)

    _value_check = models.Constraint("CHECK (value >= 0)", "Supplement value cannot be negative.")
    _category_unique = models.Constraint(
        "unique (property_id, room_type_id, guest_category)",
        "Only one supplement is allowed per room type and guest category.",
    )

    @api.constrains("property_id", "room_type_id", "charge_type", "value")
    def _check_values(self):
        for supplement in self:
            if (
                supplement.room_type_id.property_id
                and supplement.room_type_id.property_id != supplement.property_id
            ):
                raise ValidationError(_("The supplement room type belongs to another hotel."))
            if supplement.charge_type == "percent" and supplement.value > 100:
                raise ValidationError(_("A guest supplement percentage cannot exceed 100%."))


class HotelBookingSource(models.Model):
    _name = "hotel.booking.source"
    _description = "Hotel Booking Source Configuration"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    source = fields.Selection(
        [
            ("direct", "Direct"),
            ("website", "Website"),
            ("agent", "Agent"),
            ("ota_manual", "OTA (Manual)"),
            ("other", "Other"),
        ],
        required=True,
        default="direct",
    )
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
        ondelete="cascade",
    )
    company_id = fields.Many2one(related="property_id.company_id", store=True)
    pricelist_id = fields.Many2one(
        "product.pricelist",
        required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )
    active = fields.Boolean(default=True)

    _source_unique = models.Constraint(
        "UNIQUE(property_id, source)",
        "A hotel can have only one pricing configuration per booking source.",
    )

    @api.constrains("property_id", "pricelist_id")
    def _check_pricelist_company(self):
        for source in self:
            if source.pricelist_id.company_id and source.pricelist_id.company_id != source.company_id:
                raise ValidationError(_("The booking-source pricelist belongs to another company."))


class HotelReservationRateLine(models.Model):
    _name = "hotel.reservation.rate.line"
    _description = "Hotel Reservation Nightly Rate Snapshot"
    _order = "business_date, id"

    reservation_id = fields.Many2one(
        "hotel.reservation", required=True, ondelete="cascade", index=True
    )
    property_id = fields.Many2one(related="reservation_id.property_id", store=True)
    business_date = fields.Date(required=True, index=True)
    currency_id = fields.Many2one("res.currency", required=True)
    base_amount = fields.Monetary(currency_field="currency_id", required=True)
    hotel_rate_rule_id = fields.Many2one("hotel.rate.rule", readonly=True)
    occupancy_band_id = fields.Many2one("hotel.rate.occupancy.band", readonly=True)
    occupancy_multiplier = fields.Float(default=1.0, required=True, readonly=True)
    pricelist_item_id = fields.Many2one("product.pricelist.item", readonly=True)
    fiscal_position_id = fields.Many2one("account.fiscal.position", readonly=True)
    room_amount = fields.Monetary(currency_field="currency_id", required=True)
    supplement_amount = fields.Monetary(currency_field="currency_id", default=0.0)
    supplement_trace = fields.Json(readonly=True)
    tax_amount = fields.Monetary(currency_field="currency_id", default=0.0)
    amount_untaxed = fields.Monetary(currency_field="currency_id", required=True)
    amount_total = fields.Monetary(currency_field="currency_id", required=True)
    tax_ids = fields.Many2many("account.tax", string="Taxes", readonly=True)
    posted = fields.Boolean(default=False, readonly=True, copy=False)
    legacy_snapshot = fields.Boolean(default=False, readonly=True, copy=False)
    superseded = fields.Boolean(default=False, readonly=True, copy=False, index=True)
    superseded_at = fields.Datetime(readonly=True, copy=False)
    amendment_id = fields.Many2one(
        "hotel.reservation.amendment", readonly=True, copy=False, ondelete="restrict"
    )
    reversal_of_id = fields.Many2one(
        "hotel.reservation.rate.line", readonly=True, copy=False, ondelete="restrict"
    )

    _reservation_date_unique = models.UniqueIndex(
        "(reservation_id, business_date) WHERE superseded IS FALSE AND reversal_of_id IS NULL",
        "A reservation can have only one rate snapshot per business night.",
    )

    def write(self, vals):
        raise UserError(_("Nightly rate snapshots are controlled by hotel workflows."))

    def _mark_posted(self):
        return super(HotelReservationRateLine, self).write({"posted": True})

    def _supersede(self, amendment):
        return super(HotelReservationRateLine, self).write(
            {
                "superseded": True,
                "superseded_at": fields.Datetime.now(),
                "amendment_id": amendment.id,
            }
        )

    @api.ondelete(at_uninstall=False)
    def _unlink_locked_lines(self):
        if self.filtered(lambda line: line.reservation_id.rate_locked):
            raise UserError(_("Locked nightly rate snapshots cannot be deleted."))


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    base = fields.Selection(
        selection_add=[("hotel_rate", "Hotel Nightly Rate")],
        ondelete={"hotel_rate": "set default"},
    )
    hotel_seasonal_pricing_id = fields.Many2one(
        "hotel.seasonal.pricing", string="Hotel Seasonal Plan", ondelete="set null"
    )
    hotel_weekday_ids = fields.Many2many(
        "hotel.rate.weekday", string="Hotel Weekdays"
    )

    @api.constrains("hotel_seasonal_pricing_id", "pricelist_id")
    def _check_hotel_seasonal_pricelist_company(self):
        for item in self.filtered("hotel_seasonal_pricing_id"):
            pricelist_company = item.pricelist_id.company_id
            plan_company = item.hotel_seasonal_pricing_id.property_id.company_id
            if pricelist_company and pricelist_company != plan_company:
                raise ValidationError(
                    _("The pricelist rule and seasonal plan must use the same company.")
                )

    def _compute_base_price(self, product, quantity, uom, date, currency, **kwargs):
        hotel_base_price = kwargs.get("hotel_base_price")
        if hotel_base_price is not None and (not self or self.base == "hotel_rate"):
            source_currency = kwargs.get("hotel_base_currency") or currency
            if source_currency != currency:
                return source_currency._convert(
                    hotel_base_price,
                    currency,
                    self.env.company,
                    fields.Date.to_date(date),
                    round=False,
                )
            return hotel_base_price
        return super()._compute_base_price(
            product, quantity, uom, date, currency, **kwargs
        )


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    hotel_website_published = fields.Boolean(
        string="Published for Hotel Website",
        default=False,
        help="Allow public hotel guests to select this pricelist.",
    )

    def _get_applicable_rules(self, products, date, **kwargs):
        rules = super()._get_applicable_rules(products, date, **kwargs)
        if kwargs.get("hotel_pricing"):
            pricing_date = fields.Datetime.to_datetime(date).date()
            weekday = str(pricing_date.weekday())
            rules = rules.filtered(
                lambda rule: (
                    not rule.hotel_seasonal_pricing_id
                    or (
                        rule.hotel_seasonal_pricing_id.state == "active"
                        and rule.hotel_seasonal_pricing_id.date_start <= pricing_date
                        <= rule.hotel_seasonal_pricing_id.date_end
                    )
                )
                and (
                    not rule.hotel_weekday_ids
                    or weekday in rule.hotel_weekday_ids.mapped("code")
                )
            )
        return rules


class HotelRateQuote(models.AbstractModel):
    _name = "hotel.rate.quote"
    _description = "Hotel Rate Quote Service"

    @api.model
    def quote(
        self,
        property_id,
        room_type_id,
        checkin_date,
        checkout_date,
        partner_id=None,
        pricelist_id=None,
        adults=1,
        teenagers=0,
        children=0,
        infants=0,
        nationality_id=None,
        exclude_reservation_id=None,
    ):
        prop = self.env["hotel.property"].browse(property_id).exists()
        room_type = self.env["hotel.room.type"].browse(room_type_id).exists()
        partner = self.env["res.partner"].browse(partner_id).exists()
        pricelist = self.env["product.pricelist"].browse(pricelist_id).exists()
        if not prop or not room_type or not checkin_date or not checkout_date:
            raise ValidationError(_("A hotel, room type, arrival, and departure are required."))
        checkin_date = fields.Datetime.to_datetime(checkin_date)
        checkout_date = fields.Datetime.to_datetime(checkout_date)
        start_date = prop.get_business_date(checkin_date)
        end_date = prop.get_business_date(checkout_date)
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        currency = pricelist.currency_id or prop.company_id.currency_id
        guest_counts = {
            "adult": adults,
            "teenager": teenagers,
            "child": children,
            "infant": infants,
        }
        base_counts = {
            "adult": room_type.base_adults,
            "teenager": room_type.base_teenagers,
            "child": room_type.base_children,
            "infant": room_type.base_infants,
        }
        supplements = self.env["hotel.guest.supplement"].search(
            [
                ("property_id", "=", prop.id),
                ("room_type_id", "=", room_type.id),
                ("active", "=", True),
            ]
        )
        supplement_by_category = {item.guest_category: item for item in supplements}
        nationality = (
            self.env["res.country"].browse(nationality_id).code
            if nationality_id
            else partner.guest_nationality_id.code if partner else False
        )
        nights = []
        current_date = start_date
        while current_date < end_date:
            rule_domain = [
                "|",
                ("seasonal_pricing_id", "=", False),
                ("seasonal_pricing_id.state", "=", "active"),
                ("property_id", "=", prop.id),
                ("room_type_id", "=", room_type.id),
                ("date_start", "<=", current_date),
                ("date_end", ">=", current_date),
            ]
            if nationality == "LY":
                rule_domain.append(("guest_type", "in", ("all", "local")))
            elif nationality:
                rule_domain.append(("guest_type", "in", ("all", "foreign")))
            else:
                rule_domain.append(("guest_type", "=", "all"))
            weekday = str(current_date.weekday())
            rate_rule = self.env["hotel.rate.rule"].search(
                rule_domain, order="sequence, id"
            ).filtered(
                lambda rule: not rule.weekday_ids or weekday in rule.weekday_ids.mapped("code")
            )[:1]
            base_amount = room_type.base_price
            source_currency = prop.company_id.currency_id
            if rate_rule:
                base_amount = rate_rule.rate_price
                source_currency = rate_rule.currency_id
            if source_currency != currency:
                base_amount = source_currency._convert(
                    base_amount, currency, prop.company_id, current_date
                )
            night_start, night_end = prop.get_business_day_bounds(current_date)
            occupied_domain = [
                ("property_id", "=", prop.id),
                ("state", "in", ("pending_payment", "confirmed", "checked_in")),
                ("checkin_date", "<", night_end),
                ("checkout_date", ">", night_start),
            ]
            if exclude_reservation_id:
                occupied_domain.append(("id", "!=", exclude_reservation_id))
            occupied_rooms = self.env["hotel.reservation"].search_count(occupied_domain)
            sellable_rooms = self.env["hotel.room"].search_count(
                [("property_id", "=", prop.id), ("is_sellable", "=", True)]
            )
            occupancy_pct = 100.0 * occupied_rooms / sellable_rooms if sellable_rooms else 0.0
            occupancy_band = self.env["hotel.rate.occupancy.band"].search(
                [
                    ("property_id", "=", prop.id),
                    ("min_occupancy", "<=", occupancy_pct),
                    ("max_occupancy", ">=", occupancy_pct),
                ],
                limit=1,
            )
            occupancy_multiplier = occupancy_band.multiplier if occupancy_band else 1.0
            adjusted_base = base_amount * occupancy_multiplier
            room_amount = adjusted_base
            pricelist_item = self.env["product.pricelist.item"]
            if pricelist and room_type.product_id:
                room_amount, pricelist_item_id = pricelist._get_product_price_rule(
                    room_type.product_id,
                    1.0,
                    currency=currency,
                    date=night_start,
                    hotel_pricing=True,
                    hotel_base_price=adjusted_base,
                    hotel_base_currency=currency,
                )
                pricelist_item = self.env["product.pricelist.item"].browse(
                    pricelist_item_id
                )
            supplement_amount = 0.0
            supplement_trace = []
            for category, count in guest_counts.items():
                extra_count = max(count - base_counts[category], 0)
                supplement = supplement_by_category.get(category)
                if not extra_count or not supplement:
                    continue
                unit = (
                    prop.company_id.currency_id._convert(
                        supplement.value,
                        currency,
                        prop.company_id,
                        current_date,
                    )
                    if supplement.charge_type == "fixed"
                    else room_amount * supplement.value / 100.0
                )
                line_supplement = extra_count * unit
                supplement_amount += line_supplement
                supplement_trace.append(
                    {
                        "supplement_id": supplement.id,
                        "category": category,
                        "extra_guest_count": extra_count,
                        "charge_type": supplement.charge_type,
                        "unit_amount": unit,
                        "amount": line_supplement,
                    }
                )
            amount_untaxed = room_amount + supplement_amount
            tax_ids = []
            tax_amount = 0.0
            amount_total = amount_untaxed
            product = room_type.product_id
            fiscal_position = self.env["account.fiscal.position"]
            if product and "taxes_id" in product._fields:
                taxes = product.taxes_id.filtered(
                    lambda tax: not tax.company_id or tax.company_id == prop.company_id
                )
                fiscal_position = (
                    self.env["account.fiscal.position"].with_company(
                        prop.company_id
                    )._get_fiscal_position(partner)
                    if partner
                    else self.env["account.fiscal.position"]
                )
                if fiscal_position:
                    taxes = fiscal_position.map_tax(taxes)
                if taxes:
                    tax_result = taxes.compute_all(
                        amount_untaxed,
                        currency,
                        1.0,
                        product=product,
                        partner=partner,
                    )
                    tax_ids = taxes.ids
                    amount_total = tax_result["total_included"]
                    tax_amount = amount_total - tax_result["total_excluded"]
            nights.append(
                {
                    "business_date": current_date,
                    "currency_id": currency.id,
                    "base_amount": base_amount,
                    "hotel_rate_rule_id": rate_rule.id,
                    "occupancy_band_id": occupancy_band.id,
                    "occupancy_multiplier": occupancy_multiplier,
                    "pricelist_item_id": pricelist_item.id,
                    "fiscal_position_id": fiscal_position.id,
                    "room_amount": room_amount,
                    "supplement_amount": supplement_amount,
                    "supplement_trace": supplement_trace,
                    "tax_amount": tax_amount,
                    "amount_untaxed": amount_untaxed,
                    "amount_total": amount_total,
                    "tax_ids": tax_ids,
                }
            )
            current_date += timedelta(days=1)
        return {
            "property_id": prop.id,
            "room_type_id": room_type.id,
            "pricelist_id": pricelist.id,
            "currency_id": currency.id,
            "nights": nights,
            "rule_trace": [
                {
                    "business_date": fields.Date.to_string(line["business_date"]),
                    "hotel_rate_rule_id": line["hotel_rate_rule_id"],
                    "occupancy_band_id": line["occupancy_band_id"],
                    "occupancy_multiplier": line["occupancy_multiplier"],
                    "pricelist_item_id": line["pricelist_item_id"],
                    "fiscal_position_id": line["fiscal_position_id"],
                    "supplements": line["supplement_trace"],
                    "tax_ids": line["tax_ids"],
                }
                for line in nights
            ],
            "amount_untaxed": sum(line["amount_untaxed"] for line in nights),
            "supplement_amount": sum(
                line["supplement_amount"] for line in nights
            ),
            "tax_amount": sum(line["tax_amount"] for line in nights),
            "amount_total": sum(line["amount_total"] for line in nights),
        }
