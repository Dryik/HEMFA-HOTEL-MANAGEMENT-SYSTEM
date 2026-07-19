from collections import defaultdict

from odoo import _, fields, models
from odoo.exceptions import UserError


class HotelReservationAmendment(models.Model):
    _inherit = "hotel.reservation.amendment"

    generated_folio_line_ids = fields.One2many(
        "hotel.folio.line", "amendment_id", string="Generated Folio Lines", readonly=True
    )

    def _apply_financial_effects(self, before, after):
        result = super()._apply_financial_effects(before, after)
        self.ensure_one()
        reservation = self.reservation_id
        uses_rate_snapshots = "rate_line_ids" in reservation._fields
        amendment_rates = (
            reservation.rate_line_ids.filtered(
                lambda line: line.amendment_id == self and line.posted
            )
            if uses_rate_snapshots
            else False
        )
        difference = (
            sum(amendment_rates.mapped("amount_untaxed"))
            if uses_rate_snapshots
            else after["amount_total"] - before["amount_total"]
        )
        currency = reservation.currency_id
        if currency.is_zero(difference):
            return result
        folio = self.reservation_id.folio_ids[:1]
        product = self.reservation_id.room_type_id.product_id
        if not folio or not product:
            raise UserError(
                _("The amended stay requires a folio and room-rate product.")
            )
        line = folio._add_workflow_charge(
            product,
            qty=1.0,
            price_unit=difference,
            date=self.effective_date,
            source_type="amendment",
            source_reference=self.name,
            source_key=f"amendment:{self.id}",
        )
        for charge_line in line:
            charge_line._set_amendment_source(self)
        return result


class HotelFolioLine(models.Model):
    _inherit = "hotel.folio.line"

    amendment_id = fields.Many2one(
        "hotel.reservation.amendment", readonly=True, copy=False, index=True
    )


class HotelReservationGroup(models.Model):
    _inherit = "hotel.reservation.group"

    invoice_ids = fields.Many2many(
        "account.move",
        "hotel_reservation_group_invoice_rel",
        "group_id",
        "invoice_id",
        readonly=True,
    )

    def action_create_group_invoice(self):
        """Create one combined group invoice per folio currency."""
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_accountant"):
            raise UserError(_("Only a Hotel Accountant or Manager can create hotel invoices."))
        folios = self.member_ids.mapped("folio_ids")
        lines = folios.mapped("line_ids").filtered(
            lambda line: line.invoiceable
            and not line.invoice_line_id
            and not line.accounting_move_id
        )
        if not lines:
            raise UserError(_("No invoiceable group folio lines are available."))
        lines_by_currency = defaultdict(lambda: self.env["hotel.folio.line"])
        for line in lines:
            lines_by_currency[line.currency_id] |= line
        invoices = self.env["account.move"]
        for currency, currency_lines in lines_by_currency.items():
            invoice = self.env["account.move"].create(
                {
                    "move_type": "out_invoice",
                    "partner_id": self.billing_partner_id.id,
                    "currency_id": currency.id,
                    "company_id": self.property_id.company_id.id,
                    "hotel_property_id": self.property_id.id,
                    "hotel_reservation_group_id": self.id,
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": line.product_id.id,
                                "name": f"{line.folio_id.name} — {line.name}",
                                "quantity": line.qty,
                                "price_unit": line.price_unit,
                                "discount": line.discount,
                                "tax_ids": [(6, 0, line.tax_ids.ids)],
                            },
                        )
                        for line in currency_lines
                    ],
                }
            )
            self._link_group_invoice(invoice)
            for folio in currency_lines.mapped("folio_id"):
                folio._link_account_move(invoice)
            for line, invoice_line in zip(currency_lines, invoice.invoice_line_ids):
                line._link_invoice_line(invoice_line)
            invoices |= invoice
        if len(invoices) > 1:
            return {
                "name": _("Combined Group Invoices"),
                "type": "ir.actions.act_window",
                "res_model": "account.move",
                "view_mode": "list,form",
                "domain": [("id", "in", invoices.ids)],
            }
        invoice = invoices[:1]
        return {
            "name": _("Combined Group Invoice"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": invoice.id,
        }

    def action_create_isolated_invoices(self):
        """Create separate accounting documents for every room folio/payee."""
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_accountant"):
            raise UserError(_("Only a Hotel Accountant or Manager can create hotel invoices."))
        invoices_before = self.member_ids.mapped("folio_ids.invoice_ids")
        created_any = False
        for folio in self.member_ids.mapped("folio_ids"):
            payees = folio.line_ids.filtered(
                lambda line: line.invoiceable
                and not line.invoice_line_id
                and not line.accounting_move_id
            ).mapped("payee_partner_id")
            for payee in payees:
                folio.action_create_invoice(partner_id=payee)
                created_any = True
        if not created_any:
            raise UserError(_("No invoiceable room-folio lines are available."))
        invoices = self.member_ids.mapped("folio_ids.invoice_ids") - invoices_before
        return {
            "name": _("Isolated Room Invoices"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", invoices.ids)],
        }

    def _link_group_invoice(self, invoice):
        self.ensure_one()
        invoice.ensure_one()
        if (
            invoice.hotel_reservation_group_id != self
            or invoice.hotel_property_id != self.property_id
        ):
            raise UserError(_("The accounting document does not belong to this group."))
        return super(HotelReservationGroup, self).write(
            {"invoice_ids": [(4, invoice.id)]}
        )

    def write(self, vals):
        if "invoice_ids" in vals:
            raise UserError(
                _("Group invoice links can only be changed by the group invoice workflow.")
            )
        return super().write(vals)
