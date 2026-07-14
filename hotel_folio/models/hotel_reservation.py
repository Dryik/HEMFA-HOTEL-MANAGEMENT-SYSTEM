from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    folio_ids = fields.One2many(
        "hotel.folio", "reservation_id", string="Folios"
    )
    folio_count = fields.Integer(
        string="Folio Count", compute="_compute_folio_count"
    )
    checkout_balance_override_reason = fields.Text(
        string="Balance Override Reason",
        groups="hotel_base.group_hotel_manager",
        copy=False,
    )

    @api.depends("folio_ids")
    def _compute_folio_count(self):
        for rec in self:
            rec.folio_count = len(rec.folio_ids)

    def action_confirm(self):
        super().action_confirm()
        for rec in self:
            if not rec.folio_ids:
                self.env["hotel.folio"].create(
                    {
                        "reservation_id": rec.id,
                    }
                )
        self._ensure_stay_charge()

    def _ensure_stay_charge(self):
        """Post the remaining contracted stay once confirmation is complete."""
        for reservation in self:
            if not reservation.folio_ids or not reservation.room_type_id.product_id:
                continue
            folio = reservation.folio_ids[:1]
            room_lines = folio.line_ids.filtered(
                lambda line: line.source_type == "room_night"
                and not line.reversal_of_id
                and line.qty > 0
            )
            policy_reversals = room_lines.mapped("reversal_line_ids").filtered(
                lambda line: (line.source_key or "").startswith("stay_reversal:")
            )
            remaining_nights = max(
                float(reservation.nights)
                - sum(room_lines.mapped("qty"))
                - sum(policy_reversals.mapped("qty")),
                0.0,
            )
            if float_is_zero(
                remaining_nights, precision_rounding=reservation.currency_id.rounding
            ):
                continue
            source_key = f"stay:{reservation.id}"
            if self.env["hotel.folio.line"].search_count(
                [("source_key", "=", source_key)]
            ):
                source_key = f"stay:{reservation.id}:remaining:{len(room_lines)}"
            folio._add_workflow_charge(
                reservation.room_type_id.product_id,
                qty=remaining_nights,
                price_unit=reservation.rate_night,
                date=reservation.checkin_date,
                source_type="room_night",
                source_reference=reservation.name,
                source_key=source_key,
            )

    def _reverse_stay_charge(self, policy_type):
        for reservation in self:
            if not reservation.folio_ids:
                continue
            folio = reservation.folio_ids[:1]
            stay_lines = folio.line_ids.filtered(
                lambda line: line.source_type == "room_night"
                and not line.reversal_of_id
                and line.qty > 0
            )
            for line in stay_lines:
                reversal_key = (
                    f"stay_reversal:{policy_type}:{reservation.id}:{line.id}"
                )
                if self.env["hotel.folio.line"].search_count(
                    [("source_key", "=", reversal_key)]
                ):
                    continue
                reversal = folio._add_workflow_charge(
                    line.product_id,
                    qty=-line.qty,
                    price_unit=line.price_unit,
                    date=fields.Datetime.now(),
                    discount=line.discount,
                    tax_ids=line.tax_ids.ids,
                    source_type="reversal",
                    source_reference=reservation.name,
                    source_key=reversal_key,
                    invoiceable=line.invoiceable,
                    payee=line.payee_partner_id,
                )
                reversal._link_stay_reversal(
                    line,
                    _("Stay charge reversed by the %(policy)s workflow.", policy=policy_type),
                )

    def action_view_folios(self):
        self.ensure_one()
        action = {
            "name": _("Folios"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.folio",
            "view_mode": "list,form",
            "domain": [("reservation_id", "=", self.id)],
            "context": {"default_reservation_id": self.id},
        }
        if len(self.folio_ids) == 1:
            action.update(
                {
                    "view_mode": "form",
                    "res_id": self.folio_ids[0].id,
                }
            )
        return action

    def action_check_out(self):
        for reservation in self:
            open_due = sum(reservation.folio_ids.mapped("amount_due"))
            rounding = reservation.currency_id.rounding
            if not float_is_zero(open_due, precision_rounding=rounding):
                is_manager = self.env.user.has_group("hotel_base.group_hotel_manager")
                reason = (reservation.checkout_balance_override_reason or "").strip()
                if not is_manager or not reason:
                    raise UserError(
                        _(
                            "Settle the folio before checkout. A Hotel Manager may "
                            "override a remaining balance only with a recorded reason."
                        )
                    )
                reservation.message_post(
                    body=_(
                        "Checkout with balance %(amount)s approved by %(user)s. "
                        "Reason: %(reason)s",
                        amount=open_due,
                        user=self.env.user.name,
                        reason=reason,
                    )
                )
        return super().action_check_out()

    def action_cancel(self):
        candidates = self.filtered(lambda reservation: reservation.state == "confirmed")
        result = super().action_cancel()
        candidates._reverse_stay_charge("cancellation")
        candidates._apply_stay_policy_charge("cancellation")
        return result

    def action_no_show(self):
        candidates = self.filtered(lambda reservation: reservation.state == "confirmed")
        result = super().action_no_show()
        candidates._reverse_stay_charge("no_show")
        candidates._apply_stay_policy_charge("no_show")
        return result

    def _apply_stay_policy_charge(self, policy_type):
        for reservation in self:
            prop = reservation.property_id
            policy = prop.cancellation_policy if policy_type == "cancellation" else prop.no_show_policy
            if policy == "none":
                continue
            product = (
                prop.cancellation_fee_product_id
                if policy_type == "cancellation"
                else prop.no_show_fee_product_id
            )
            if not product:
                raise UserError(
                    _("Configure the %(policy)s fee product before enabling this policy.", policy=policy_type)
                )
            if policy_type == "cancellation" and prop.cancellation_grace_hours:
                cutoff = reservation.checkin_date - timedelta(
                    hours=prop.cancellation_grace_hours
                )
                if fields.Datetime.now() < cutoff:
                    continue
            if policy == "fixed":
                amount = (
                    prop.cancellation_fee_value
                    if policy_type == "cancellation"
                    else prop.no_show_fee_value
                )
            elif policy == "first_night":
                amount = reservation.rate_night
            else:
                percentage = (
                    prop.cancellation_fee_value
                    if policy_type == "cancellation"
                    else prop.no_show_fee_value
                )
                amount = reservation.amount_total * percentage / 100.0
            if reservation.folio_ids and amount:
                reservation.folio_ids[:1]._add_workflow_charge(
                    product,
                    qty=1.0,
                    price_unit=amount,
                    source_type="stay_policy",
                    source_reference=reservation.name,
                    source_key=f"{policy_type}:{reservation.id}",
                )
