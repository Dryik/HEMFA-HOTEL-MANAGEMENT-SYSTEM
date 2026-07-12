from odoo import _, models
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        for order in self:
            if order._room_charge_payments():
                order._post_room_charges()
        return res

    def _room_charge_payments(self):
        self.ensure_one()
        return self.payment_ids.filtered(
            lambda p: p.payment_method_id.is_room_charge
        )

    def _find_room_charge_folio(self):
        """Locate the open folio of the order's in-house guest.

        POS must never post to checked-out or closed folios: only a
        reservation currently in the checked_in state qualifies.
        Lookups run as sudo so POS cashiers do not need hotel ACLs;
        restriction enforcement still evaluates the real user.
        """
        self.ensure_one()
        if not self.partner_id:
            raise UserError(
                _(
                    "Select the hotel guest as the order's customer "
                    "before charging to a room."
                )
            )
        reservation = self.env["hotel.reservation"].sudo().search(
            [
                ("partner_id", "=", self.partner_id.id),
                ("state", "=", "checked_in"),
            ],
            order="actual_checkin desc",
            limit=1,
        )
        if not reservation:
            raise UserError(
                _(
                    "%(guest)s has no in-house reservation. Room charges "
                    "are only allowed for checked-in guests.",
                    guest=self.partner_id.name,
                )
            )
        folio = reservation.folio_ids[:1]
        if not folio:
            raise UserError(
                _(
                    "Reservation %(reservation)s has no folio to charge.",
                    reservation=reservation.name,
                )
            )
        return folio

    def _post_room_charges(self):
        """Post every order line to the guest folio.

        hotel.folio.add_charge enforces guest service restrictions and
        entity ceilings (hotel_restricted_services); a blocked service
        aborts the whole order settlement. sudo() only lifts the ACLs —
        env.user stays the cashier, so supervisor override rules apply
        unchanged.
        """
        self.ensure_one()
        # Idempotency: never post the same order twice.
        already_posted = (
            self.env["hotel.folio.line"]
            .sudo()
            .search_count([("pos_order_id", "=", self.id)])
        )
        if already_posted:
            return self.env["hotel.folio"]

        # Mixed payments would collect cash AND post the full order to
        # the folio; require the room charge to cover the whole order.
        room_charge_total = sum(self._room_charge_payments().mapped("amount"))
        if (
            self.currency_id.compare_amounts(
                room_charge_total, self.amount_total
            )
            != 0
        ):
            raise UserError(
                _(
                    "Room charge must cover the whole order. Mixed "
                    "payments (part cash, part room) are not supported."
                )
            )

        folio = self._find_room_charge_folio()
        for line in self.lines:
            folio_line = folio.sudo().add_charge(
                line.product_id,
                qty=line.qty,
                price_unit=line.price_unit,
                date=self.date_order,
            )
            folio_line.pos_order_id = self.id
        folio.sudo().message_post(
            body=_(
                "POS order %(order)s charged to room (%(amount)s, "
                "%(count)s lines).",
                order=self.name,
                amount=self.amount_total,
                count=len(self.lines),
            )
        )
        return folio
