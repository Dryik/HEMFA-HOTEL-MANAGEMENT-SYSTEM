from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    hotel_room_charge_move_id = fields.Many2one(
        "account.move", string="Room-charge Transfer", readonly=True, copy=False
    )

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        for order in self:
            if order._room_charge_payments():
                order._post_room_charges()
        return result

    def _room_charge_payments(self):
        self.ensure_one()
        return self.payment_ids.filtered(
            lambda payment: payment.payment_method_id.is_room_charge
        )

    def _find_room_charge_folio(self):
        self.ensure_one()
        prop = self.config_id.hotel_property_id
        if not prop:
            raise UserError(_("Select a hotel property on the POS configuration."))
        if not self.partner_id:
            raise UserError(
                _(
                    "Select the hotel guest as the order's customer before "
                    "charging to a room."
                )
            )
        reservation = self.env["hotel.reservation"].sudo().search(
            [
                ("partner_id", "=", self.partner_id.id),
                ("property_id", "=", prop.id),
                ("state", "=", "checked_in"),
            ],
            order="actual_checkin desc",
            limit=1,
        )
        if not reservation:
            raise UserError(
                _(
                    "%(guest)s has no in-house reservation at %(property)s. "
                    "Room charges are only allowed for checked-in guests.",
                    guest=self.partner_id.name,
                    property=prop.display_name,
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
        self.ensure_one()
        already_posted = self.env["hotel.folio.line"].sudo().search_count(
            [("pos_order_id", "=", self.id)]
        )
        if already_posted:
            return self.env["hotel.folio"]

        room_charge_total = sum(self._room_charge_payments().mapped("amount"))
        if self.currency_id.compare_amounts(room_charge_total, self.amount_total) != 0:
            raise UserError(
                _(
                    "Room charge must cover the whole order. Mixed payments "
                    "(part cash, part room) are not supported."
                )
            )

        folio = self._find_room_charge_folio()
        created_lines = self.env["hotel.folio.line"]
        for pos_line in self.lines:
            folio_line = folio.sudo()._add_workflow_charge(
                pos_line.product_id,
                qty=pos_line.qty,
                price_unit=pos_line.price_unit,
                date=self.date_order,
                discount=pos_line.discount,
                tax_ids=pos_line.tax_ids_after_fiscal_position.ids,
                source_type="pos",
                source_reference=self.name,
                source_key=f"pos:{pos_line.uuid}",
                invoiceable=False,
            )
            for charge_line in folio_line:
                charge_line._set_pos_source(self, pos_line)
            created_lines |= folio_line

        transfer = self._create_room_charge_transfer(folio, created_lines)
        for created_line in created_lines:
            created_line._set_operational_lock("pos", accounting_move=transfer)
        self.hotel_room_charge_move_id = transfer
        folio.sudo().message_post(
            body=_(
                "POS order %(order)s transferred from room-charge clearing "
                "to routed receivables (%(amount)s, %(count)s lines).",
                order=self.name,
                amount=self.amount_total,
                count=len(self.lines),
            )
        )
        return folio

    def _create_room_charge_transfer(self, folio, folio_lines):
        self.ensure_one()
        prop = self.config_id.hotel_property_id
        clearing = prop.room_charge_clearing_account_id
        journal = prop.room_charge_journal_id
        if not clearing or not journal:
            raise UserError(
                _("The POS property's room-charge clearing account and journal are required.")
            )
        company = prop.company_id
        currency = self.currency_id
        grouped = defaultdict(float)
        for line in folio_lines:
            grouped[line.payee_partner_id] += line.amount_total
        transfer_total = sum(grouped.values())
        if currency.compare_amounts(transfer_total, self.amount_total) != 0:
            raise UserError(
                _(
                    "Folio transfer total %(folio)s does not match POS receipt total %(pos)s.",
                    folio=transfer_total,
                    pos=self.amount_total,
                )
            )

        move_date = prop.get_business_date(self.date_order)
        move_lines = []
        company_total = 0.0
        for partner, amount_currency in grouped.items():
            company_amount = currency._convert(
                amount_currency, company.currency_id, company, move_date
            )
            company_total += company_amount
            receivable = partner.with_company(company).property_account_receivable_id
            if not receivable:
                raise UserError(
                    _("Partner %(partner)s has no receivable account.", partner=partner.name)
                )
            values = {
                "name": _("Room charge %(order)s", order=self.name),
                "account_id": receivable.id,
                "partner_id": partner.id,
                "debit": company_amount,
                "credit": 0.0,
            }
            if currency != company.currency_id:
                values.update(
                    {"currency_id": currency.id, "amount_currency": amount_currency}
                )
            move_lines.append((0, 0, values))

        clearing_values = {
            "name": _("Room charge clearing %(order)s", order=self.name),
            "account_id": clearing.id,
            "debit": 0.0,
            "credit": company_total,
        }
        if currency != company.currency_id:
            clearing_values.update(
                {"currency_id": currency.id, "amount_currency": -transfer_total}
            )
        move_lines.append((0, 0, clearing_values))
        move = self.env["account.move"].sudo().create(
            {
                "move_type": "entry",
                "journal_id": journal.id,
                "date": move_date,
                "ref": _("POS room charge %(order)s", order=self.name),
                "hotel_property_id": prop.id,
                "hotel_folio_id": folio.id,
                "line_ids": move_lines,
            }
        )
        move.action_post()
        return move
