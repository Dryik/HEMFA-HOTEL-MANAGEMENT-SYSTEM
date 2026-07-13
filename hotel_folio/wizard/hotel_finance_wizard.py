from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class HotelManualFxWizard(models.TransientModel):
    _name = "hotel.manual.fx.wizard"
    _description = "Hotel Manual FX Approval"

    move_id = fields.Many2one("account.move", required=True, readonly=True)
    old_rate = fields.Float(related="move_id.invoice_currency_rate", readonly=True)
    new_rate = fields.Float(required=True, digits=0)
    reason = fields.Text(required=True)

    @api.constrains("new_rate")
    def _check_new_rate(self):
        if any(wizard.new_rate <= 0 for wizard in self):
            raise ValidationError(_("The currency rate must be greater than zero."))

    def action_apply(self):
        self.ensure_one()
        allowed = self.env.user.has_group("hotel_base.group_hotel_accountant") or self.env.user.has_group(
            "hotel_base.group_hotel_manager"
        )
        if not allowed:
            raise UserError(_("Only a Hotel Accountant or Manager can approve manual FX."))
        if self.move_id.state != "draft" or not self.move_id.is_invoice(include_receipts=True):
            raise UserError(_("Manual FX can only be changed on a draft invoice."))
        if not self.reason.strip():
            raise UserError(_("A reason is required for a manual FX change."))
        self.move_id._apply_hotel_manual_fx(self.new_rate, self.reason)
        return {"type": "ir.actions.act_window_close"}


class HotelAllocateAdvanceWizard(models.TransientModel):
    _name = "hotel.allocate.advance.wizard"
    _description = "Allocate Hotel Deposit or Agency Advance"

    folio_id = fields.Many2one("hotel.folio", required=True, readonly=True)
    payment_id = fields.Many2one(
        "account.payment",
        required=True,
        domain="[('hotel_property_id', '=', property_id), ('hotel_payment_purpose', 'in', ('guest_deposit', 'agency_advance')), ('state', 'in', ('in_process', 'paid'))]",
    )
    invoice_id = fields.Many2one(
        "account.move",
        required=True,
        domain="[('id', 'in', invoice_ids), ('state', '=', 'posted'), ('payment_state', 'in', ('not_paid', 'partial', 'in_payment'))]",
    )
    property_id = fields.Many2one(related="folio_id.property_id")
    invoice_ids = fields.Many2many(related="folio_id.invoice_ids")

    def action_allocate(self):
        self.ensure_one()
        payment = self.payment_id
        invoice = self.invoice_id
        if payment.company_id != invoice.company_id or payment.currency_id != invoice.currency_id:
            raise UserError(_("Payment and invoice must use the same company and currency."))
        if payment.partner_id.commercial_partner_id != invoice.commercial_partner_id:
            raise UserError(_("Payment and invoice must belong to the same commercial partner."))
        if payment.hotel_folio_id and payment.hotel_folio_id != self.folio_id:
            raise UserError(_("This advance is already allocated to another folio."))
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable" and not line.reconciled
        )
        invoice_lines = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable" and not line.reconciled
        )
        if not payment_lines or not invoice_lines:
            raise UserError(_("No unreconciled receivable balance is available to allocate."))
        if float_compare(payment.hotel_available_advance, 0.0, precision_rounding=payment.currency_id.rounding) <= 0:
            raise UserError(_("This payment has no available advance balance."))
        (payment_lines | invoice_lines).reconcile()
        if not payment.hotel_folio_id:
            payment._assign_hotel_folio(self.folio_id)
        self.folio_id.message_post(
            body=_(
                "%(purpose)s %(payment)s allocated to invoice %(invoice)s by %(user)s.",
                purpose=dict(payment._fields["hotel_payment_purpose"].selection).get(
                    payment.hotel_payment_purpose
                ),
                payment=payment.display_name,
                invoice=invoice.display_name,
                user=self.env.user.name,
            )
        )
        return {"type": "ir.actions.act_window_close"}
