from odoo import _, fields, models
from odoo.exceptions import UserError


class HotelFolio(models.Model):
    _inherit = "hotel.folio"

    def add_charge(self, product, qty=1.0, price_unit=None, date=None, **kwargs):
        """Enforce guest-level blocks/limits and entity ceilings.

        Manager override: call with a ``service_override_reason`` in the
        context. Requires the FO supervisor group; the override is
        logged in the folio chatter.
        """
        return self._add_charge_with_restrictions(
            product,
            qty=qty,
            price_unit=price_unit,
            date=date,
            workflow=False,
            **kwargs,
        )

    def _add_workflow_charge(
        self, product, qty=1.0, price_unit=None, date=None, **kwargs
    ):
        return self._add_charge_with_restrictions(
            product,
            qty=qty,
            price_unit=price_unit,
            date=date,
            workflow=True,
            **kwargs,
        )

    def _add_charge_with_restrictions(
        self, product, qty=1.0, price_unit=None, date=None, workflow=False, **kwargs
    ):
        self.ensure_one()
        if workflow:
            if kwargs.get("source_type") not in {
                "room_night",
                "pos",
                "service",
                "amendment",
                "stay_policy",
                "reversal",
                "migration",
            } or not kwargs.get("source_key"):
                raise UserError(_("A valid immutable workflow source is required."))
            existing_lines = self._existing_workflow_charge_lines(
                kwargs.get("source_key")
            )
            if existing_lines:
                return existing_lines
        elif (
            kwargs.get("source_type", "manual") != "manual"
            or kwargs.get("source_reference")
            or kwargs.get("source_key")
            or kwargs.get("invoiceable") is False
        ):
            raise UserError(
                _(
                    "Operational charge sources can only be assigned by their "
                    "hotel workflows."
                )
            )

        unit_price = price_unit if price_unit is not None else product.list_price
        discount = kwargs.get("discount", 0.0)
        tax_ids = kwargs.get("tax_ids")
        taxes = (
            self.env["account.tax"].browse(tax_ids).exists()
            if tax_ids is not None
            else product.taxes_id.filtered(
                lambda tax: tax.company_id == self.property_id.company_id
            )
        )
        amount = taxes.compute_all(
            unit_price * (1.0 - discount / 100.0),
            currency=self.currency_id,
            quantity=qty,
            product=product,
            partner=self.partner_id,
        )["total_included"]
        charge_date = date or fields.Datetime.now()
        override_reason = self.env.context.get("service_override_reason")

        service_violation = self._service_charge_violation(
            product, amount, charge_date
        )
        if service_violation:
            if not override_reason:
                raise UserError(service_violation)
            if not self.env.user.has_group(
                "hotel_base.group_hotel_fo_supervisor"
            ):
                raise UserError(
                    _(
                        "%(violation)s\nOverriding a service restriction "
                        "requires the Front Office Supervisor role.",
                        violation=service_violation,
                    )
                )

        payee = self._get_charge_payee(
            product, payee=kwargs.get("payee") if workflow else None
        )
        entity_violation, split_ceiling, entity_allowance = (
            self._entity_ceiling_assessment(
                payee, product, amount, charge_date
            )
        )
        if entity_violation:
            if not override_reason:
                raise UserError(entity_violation)
            if not self.env.user.has_group(
                "hotel_base.group_hotel_fo_supervisor"
            ):
                raise UserError(
                    _(
                        "%(violation)s\nOverriding an entity ceiling "
                        "requires the Front Office Supervisor role.",
                        violation=entity_violation,
                    )
                )

        if split_ceiling and not entity_violation:
            lines = self._create_split_charge(
                product,
                qty=qty,
                price_unit=unit_price,
                charge_date=charge_date,
                amount=amount,
                entity_payee=payee,
                entity_allowance=entity_allowance,
                ceiling=split_ceiling,
                workflow=workflow,
                kwargs=kwargs,
                taxes=taxes,
            )
        elif workflow:
            lines = super()._add_workflow_charge(
                product, qty=qty, price_unit=price_unit, date=date, **kwargs
            )
        else:
            lines = super().add_charge(
                product, qty=qty, price_unit=price_unit, date=date, **kwargs
            )

        if override_reason and (service_violation or entity_violation):
            self.message_post(
                body=_(
                    "Service restriction overridden by %(user)s for "
                    "%(product)s (%(amount)s). Reason: %(reason)s",
                    user=self.env.user.name,
                    product=product.display_name,
                    amount=amount,
                    reason=override_reason,
                )
            )
        return lines

    # -- helpers -----------------------------------------------------

    def _existing_workflow_charge_lines(self, source_key):
        if not source_key:
            return self.env["hotel.folio.line"]
        return self.env["hotel.folio.line"].search(
            [
                ("folio_id", "=", self.id),
                ("source_key", "in", [source_key, f"{source_key}:guest"]),
            ],
            order="id",
        )

    def _charge_total_for_quantity(
        self, product, quantity, unit_price, discount, taxes, payee
    ):
        return taxes.compute_all(
            unit_price * (1.0 - discount / 100.0),
            currency=self.currency_id,
            quantity=quantity,
            product=product,
            partner=payee,
        )["total_included"]

    def _quantity_for_charge_total(
        self, product, target, total, qty, unit_price, discount, taxes, payee
    ):
        if self.currency_id.is_zero(target):
            return 0.0
        quantity = qty * target / total
        for _attempt in range(4):
            computed = self._charge_total_for_quantity(
                product, quantity, unit_price, discount, taxes, payee
            )
            if self.currency_id.compare_amounts(computed, target) == 0 or not computed:
                break
            quantity *= target / computed
        return quantity

    def _create_charge_portion(
        self,
        product,
        qty,
        price_unit,
        charge_date,
        payee,
        workflow,
        kwargs,
        source_key=None,
    ):
        if workflow:
            portion_kwargs = dict(kwargs)
            portion_kwargs.pop("payee", None)
            portion_kwargs.pop("source_key", None)
            return super()._add_workflow_charge(
                product,
                qty=qty,
                price_unit=price_unit,
                date=charge_date,
                payee=payee,
                source_key=source_key,
                **portion_kwargs,
            )
        return super()._add_charge_impl(
            product,
            qty=qty,
            price_unit=price_unit,
            date=charge_date,
            discount=kwargs.get("discount", 0.0),
            tax_ids=kwargs.get("tax_ids"),
            source_type="manual",
            invoiceable=True,
            payee=payee,
            workflow=False,
        )

    def _create_split_charge(
        self,
        product,
        qty,
        price_unit,
        charge_date,
        amount,
        entity_payee,
        entity_allowance,
        ceiling,
        workflow,
        kwargs,
        taxes,
    ):
        discount = kwargs.get("discount", 0.0)
        lines = self.env["hotel.folio.line"]
        base_source_key = kwargs.get("source_key")
        if self.currency_id.compare_amounts(entity_allowance, 0.0) > 0:
            entity_qty = self._quantity_for_charge_total(
                product,
                entity_allowance,
                amount,
                qty,
                price_unit,
                discount,
                taxes,
                entity_payee,
            )
            lines |= self._create_charge_portion(
                product,
                qty=entity_qty,
                price_unit=price_unit,
                charge_date=charge_date,
                payee=entity_payee,
                workflow=workflow,
                kwargs=kwargs,
                source_key=base_source_key,
            )

        entity_total = sum(lines.mapped("amount_total"))
        guest_target = self.currency_id.round(amount - entity_total)
        if self.currency_id.compare_amounts(guest_target, 0.0) > 0:
            guest_qty = self._quantity_for_charge_total(
                product,
                guest_target,
                amount,
                qty,
                price_unit,
                discount,
                taxes,
                self.partner_id,
            )
            lines |= self._create_charge_portion(
                product,
                qty=guest_qty,
                price_unit=price_unit,
                charge_date=charge_date,
                payee=self.partner_id,
                workflow=workflow,
                kwargs=kwargs,
                source_key=f"{base_source_key}:guest" if workflow else None,
            )

        guest_total = sum(
            lines.filtered(
                lambda line: line.payee_partner_id == self.partner_id
            ).mapped("amount_total")
        )
        self.message_post(
            body=_(
                "Charge %(product)s split by ceiling %(ceiling)s: total "
                "%(total)s, entity %(entity)s, guest %(guest)s.",
                product=product.display_name,
                ceiling=ceiling.display_name,
                total=self.currency_id.format(amount),
                entity=self.currency_id.format(entity_total),
                guest=self.currency_id.format(guest_total),
            )
        )
        return lines

    def _day_bounds(self, charge_date):
        self.ensure_one()
        prop = self.reservation_id.property_id
        day = prop.get_business_date(charge_date)
        return prop.get_business_day_bounds(day)

    def _category_charges(self, restriction, date_from=None, date_to=None):
        """Total already charged on this folio for a restriction's
        category, optionally within a date window."""
        lines = self.line_ids.filtered(
            lambda l: restriction.matches_product(l.product_id)
        )
        if date_from and date_to:
            lines = lines.filtered(
                lambda l: date_from <= l.date < date_to
            )
        return sum(lines.mapped("amount"))

    def _service_charge_violation(self, product, amount, charge_date):
        """Return an error message when the charge violates a guest
        restriction, else False."""
        self.ensure_one()
        restrictions = self.reservation_id.service_restriction_ids.filtered(
            lambda r: r.matches_product(product)
        )
        for restriction in restrictions:
            if restriction.restriction_type == "blocked":
                return _(
                    "Service '%(category)s' is blocked for guest "
                    "%(guest)s on this stay.",
                    category=restriction.category_id.display_name,
                    guest=self.partner_id.name,
                )
            if restriction.daily_limit:
                day_start, day_end = self._day_bounds(charge_date)
                charged = self._category_charges(
                    restriction, day_start, day_end
                )
                if (
                    self.currency_id.compare_amounts(
                        charged + amount, restriction.daily_limit
                    )
                    > 0
                ):
                    return _(
                        "Daily limit of %(limit)s for '%(category)s' "
                        "exceeded (already charged %(charged)s, new "
                        "charge %(amount)s).",
                        limit=restriction.daily_limit,
                        category=restriction.category_id.display_name,
                        charged=charged,
                        amount=amount,
                    )
            if restriction.stay_limit:
                charged = self._category_charges(restriction)
                if (
                    self.currency_id.compare_amounts(
                        charged + amount, restriction.stay_limit
                    )
                    > 0
                ):
                    return _(
                        "Stay limit of %(limit)s for '%(category)s' "
                        "exceeded (already charged %(charged)s, new "
                        "charge %(amount)s).",
                        limit=restriction.stay_limit,
                        category=restriction.category_id.display_name,
                        charged=charged,
                        amount=amount,
                    )
        return False

    def _entity_ceiling_assessment(self, payee, product, amount, charge_date):
        """Return block violation and the limiting charge-guest allowance."""
        self.ensure_one()
        if (
            self.currency_id.compare_amounts(amount, 0.0) <= 0
            or not payee.sudo().is_hotel_agency
        ):
            return False, self.env["hotel.entity.service.ceiling"], amount
        ceilings = payee.sudo().service_ceiling_ids.filtered(
            lambda c: c.active
            and c.daily_limit
            and c.property_id == self.property_id
            and c.matches_product(product)
        )
        if not ceilings:
            return False, ceilings, amount
        # Odoo transactions use REPEATABLE READ.  SELECT ... FOR UPDATE
        # alone can wait and then continue with a stale snapshot, allowing
        # two concurrent charges to validate the same remaining ceiling.
        # A no-op row update creates a write/write conflict instead; Odoo
        # retries the losing request with a fresh snapshot.
        self.env.cr.execute(
            "UPDATE hotel_entity_service_ceiling SET id = id WHERE id IN %s",
            [tuple(ceilings.ids)],
        )
        day_start, day_end = self._day_bounds(charge_date)
        candidate_lines = self.env["hotel.folio.line"].sudo().search(
            [
                ("folio_id.property_id", "=", self.property_id.id),
                ("payee_partner_id", "=", payee.id),
                ("date", ">=", day_start),
                ("date", "<", day_end),
            ]
        )
        block_violation = False
        split_ceiling = self.env["hotel.entity.service.ceiling"]
        entity_allowance = amount
        business_date = self.property_id.get_business_date(charge_date)
        for ceiling in ceilings:
            matching_lines = candidate_lines.filtered(
                lambda candidate: ceiling.matches_product(candidate.product_id)
            )
            billed = sum(
                candidate.currency_id._convert(
                    candidate.amount_total,
                    ceiling.currency_id,
                    self.property_id.company_id,
                    self.property_id.get_business_date(candidate.date),
                )
                for candidate in matching_lines
            )
            charge_amount = self.currency_id._convert(
                amount,
                ceiling.currency_id,
                self.property_id.company_id,
                business_date,
            )
            prospective_billed = billed + charge_amount
            if ceiling.currency_id.compare_amounts(
                prospective_billed, ceiling.daily_limit
            ) <= 0:
                continue
            if ceiling.on_excess != "charge_guest":
                block_violation = block_violation or _(
                    "Daily ceiling of %(limit)s for entity %(entity)s "
                    "(%(category)s) exceeded: %(billed)s billed today "
                    "across this property.",
                    limit=ceiling.daily_limit,
                    entity=payee.name,
                    category=ceiling.product_id.display_name
                    or _("All Services"),
                    billed=prospective_billed,
                )
                continue

            remaining = max(
                ceiling.currency_id.round(ceiling.daily_limit - billed),
                0.0,
            )
            allowed = ceiling.currency_id._convert(
                remaining,
                self.currency_id,
                self.property_id.company_id,
                business_date,
            )
            allowed = min(max(self.currency_id.round(allowed), 0.0), amount)
            if not split_ceiling or self.currency_id.compare_amounts(
                allowed, entity_allowance
            ) < 0:
                split_ceiling = ceiling
                entity_allowance = allowed
        return block_violation, split_ceiling, entity_allowance
