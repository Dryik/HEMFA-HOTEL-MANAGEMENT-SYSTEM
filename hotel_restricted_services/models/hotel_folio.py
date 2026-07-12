from datetime import datetime, time, timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError


class HotelFolio(models.Model):
    _inherit = "hotel.folio"

    def add_charge(self, product, qty=1.0, price_unit=None, date=None):
        """Enforce guest-level blocks/limits and entity ceilings.

        Manager override: call with a ``service_override_reason`` in the
        context. Requires the FO supervisor group; the override is
        logged in the folio chatter.
        """
        self.ensure_one()
        amount = (
            price_unit if price_unit is not None else product.list_price
        ) * qty
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

        line = super().add_charge(
            product, qty=qty, price_unit=price_unit, date=date
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

    @staticmethod
    def _day_bounds(charge_date):
        day = (
            charge_date.date()
            if isinstance(charge_date, datetime)
            else charge_date
        )
        start = datetime.combine(day, time.min)
        return start, start + timedelta(days=1)

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
            and c.matches_product(line.product_id)
        )
        for ceiling in ceilings:
            day_start, day_end = self._day_bounds(line.date)
            billed = sum(
                self.line_ids.filtered(
                    lambda l: l.payee_partner_id == payee
                    and ceiling.matches_product(l.product_id)
                    and day_start <= l.date < day_end
                ).mapped("amount")
            )
            if (
                self.currency_id.compare_amounts(
                    billed, ceiling.daily_limit
                )
                > 0
            ):
                return _(
                    "Daily ceiling of %(limit)s for entity %(entity)s "
                    "(%(category)s) exceeded: %(billed)s billed today "
                    "on this folio.",
                    limit=ceiling.daily_limit,
                    entity=payee.name,
                    category=ceiling.category_id.display_name
                    or _("All Services"),
                    billed=billed,
                )
        return False
