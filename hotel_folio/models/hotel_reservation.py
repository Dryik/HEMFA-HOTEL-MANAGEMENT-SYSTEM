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
        candidates._apply_stay_policy_charge("cancellation")
        return result

    def action_no_show(self):
        candidates = self.filtered(lambda reservation: reservation.state == "confirmed")
        result = super().action_no_show()
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
