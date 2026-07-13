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

        violation = self._service_charge_violation(
            product, amount, charge_date
        )
        if violation:
            if not override_reason:
                raise UserError(violation)
            if not self.env.user.has_group(
                "hotel_base.group_hotel_fo_supervisor"
            ):
                raise UserError(
                    _(
                        "%(violation)s\nOverriding a service restriction "
                        "requires the Front Office Supervisor role.",
                        violation=violation,
                    )
                )

        if workflow:
            line = super()._add_workflow_charge(
                product, qty=qty, price_unit=price_unit, date=date, **kwargs
            )
        else:
            line = super().add_charge(
                product, qty=qty, price_unit=price_unit, date=date, **kwargs
            )

        entity_violation = self._entity_ceiling_violation(line)
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

        if override_reason and (violation or entity_violation):
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
        return line

    # -- helpers -----------------------------------------------------

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

    def _entity_ceiling_violation(self, line):
        """Return an error message when the freshly created line pushes
        the payee entity over one of its ceilings, else False."""
        self.ensure_one()
        payee = line.payee_partner_id
        if not payee.is_hotel_agency:
            return False
        ceilings = payee.service_ceiling_ids.filtered(
            lambda c: c.active
            and c.daily_limit
            and c.property_id == self.property_id
            and c.matches_product(line.product_id)
        )
        if ceilings:
            # Odoo transactions use REPEATABLE READ.  SELECT ... FOR UPDATE
            # alone can wait and then continue with a stale snapshot, allowing
            # two concurrent charges to validate the same remaining ceiling.
            # A no-op row update creates a write/write conflict instead; Odoo
            # retries the losing request with a fresh snapshot.
            self.env.cr.execute(
                "UPDATE hotel_entity_service_ceiling SET id = id WHERE id IN %s",
                [tuple(ceilings.ids)],
            )
        for ceiling in ceilings:
            day_start, day_end = self._day_bounds(line.date)
            candidate_lines = self.env["hotel.folio.line"].search(
                [
                    ("folio_id.property_id", "=", self.property_id.id),
                    ("payee_partner_id", "=", payee.id),
                    ("date", ">=", day_start),
                    ("date", "<", day_end),
                ]
            )
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
            if (
                ceiling.currency_id.compare_amounts(
                    billed, ceiling.daily_limit
                )
                > 0
            ):
                return _(
                    "Daily ceiling of %(limit)s for entity %(entity)s "
                    "(%(category)s) exceeded: %(billed)s billed today "
                    "across this property.",
                    limit=ceiling.daily_limit,
                    entity=payee.name,
                    category=ceiling.category_id.display_name
                    or _("All Services"),
                    billed=billed,
                )
        return False
