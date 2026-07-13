from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelCashierPaymentWizard(models.TransientModel):
    _name = "hotel.cashier.payment.wizard"
    _description = "Collect Hotel Cashier Payment"

    session_id = fields.Many2one(
        "hotel.frontdesk.session", required=True, readonly=True
    )
    property_id = fields.Many2one(
        "hotel.property", required=True, readonly=True
    )
    folio_id = fields.Many2one(
        "hotel.folio", domain="[('property_id', '=', property_id)]"
    )
    partner_id = fields.Many2one("res.partner", required=True)
    payment_type = fields.Selection(
        [("inbound", "Receipt"), ("outbound", "Refund / Payout")],
        default="inbound",
        required=True,
    )
    purpose = fields.Selection(
        [
            ("guest_deposit", "Guest Deposit"),
            ("agency_advance", "Agency Advance"),
            ("folio_settlement", "Folio Settlement"),
            ("refund", "Guest Refund"),
            ("payout", "Cash Payout"),
        ],
        default="folio_settlement",
        required=True,
    )
    amount = fields.Monetary(required=True)
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    journal_id = fields.Many2one(
        "account.journal",
        required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('cash', 'bank'))]",
    )
    company_id = fields.Many2one(related="property_id.company_id")
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    memo = fields.Char()

    @api.onchange("folio_id")
    def _onchange_folio_id(self):
        if self.folio_id:
            self.partner_id = self.folio_id.partner_id
            self.currency_id = self.folio_id.currency_id

    @api.constrains("amount")
    def _check_amount(self):
        if any(wizard.amount <= 0.0 for wizard in self):
            raise ValidationError(_("Payment amount must be greater than zero."))

    def action_post_payment(self):
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_cashier"):
            raise UserError(_("Only a cashier can collect a session payment."))
        if self.session_id.state != "opened":
            raise UserError(_("Payments can only be collected in an open session."))
        if self.session_id.property_id != self.property_id:
            raise UserError(_("Payment and session must use the same property."))
        is_supervisor = self.env.user.has_group(
            "hotel_base.group_hotel_fo_supervisor"
        )
        if self.session_id.user_id != self.env.user and not is_supervisor:
            raise UserError(_("A cashier can collect payments only in their own session."))
        if self.journal_id.company_id != self.property_id.company_id:
            raise UserError(_("The payment journal must belong to the property company."))
        if self.folio_id and self.folio_id.property_id != self.property_id:
            raise UserError(_("The payment folio must belong to the session property."))
        if self.folio_id and self.currency_id != self.folio_id.currency_id:
            raise UserError(_("The payment and folio must use the same currency."))
        if self.purpose in ("folio_settlement", "refund") and not self.folio_id:
            raise UserError(_("Select a folio for settlements and refunds."))
        if self.payment_type == "inbound" and self.purpose in ("refund", "payout"):
            raise UserError(_("Refunds and payouts must be outbound payments."))
        if self.payment_type == "outbound" and self.purpose not in ("refund", "payout"):
            raise UserError(_("Deposits, advances, and settlements must be inbound payments."))

        payment = self.env["account.payment"].sudo().with_company(
            self.property_id.company_id
        ).create(
            {
                "payment_type": self.payment_type,
                "partner_type": "customer",
                "partner_id": self.partner_id.id,
                "amount": self.amount,
                "currency_id": self.currency_id.id,
                "journal_id": self.journal_id.id,
                "date": self.payment_date,
                "memo": self.memo,
                "hotel_property_id": self.property_id.id,
                "hotel_folio_id": self.folio_id.id,
                "hotel_frontdesk_session_id": self.session_id.id,
                "hotel_payment_purpose": self.purpose,
            }
        )
        payment.action_post()
        if self.purpose == "folio_settlement":
            self._reconcile_folio_settlement(payment)
        self.session_id.message_post(
            body=_(
                "Payment %(payment)s posted by %(user)s for %(amount)s %(currency)s.",
                payment=payment.display_name,
                user=self.env.user.name,
                amount=self.amount,
                currency=self.currency_id.name,
            )
        )
        return {"type": "ir.actions.act_window_close"}

    def _reconcile_folio_settlement(self, payment):
        """Allocate a settlement to matching posted folio receivables."""
        self.ensure_one()
        folio = self.folio_id
        document_moves = (
            folio.line_ids.mapped("invoice_line_id.move_id")
            | folio.line_ids.mapped("accounting_move_id")
        ).filtered(lambda move: move.state == "posted")
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
            and not line.reconciled
        )
        for payment_line in payment_lines:
            candidates = document_moves.line_ids.filtered(
                lambda line: line.account_id == payment_line.account_id
                and not line.reconciled
                and line.partner_id.commercial_partner_id
                == payment.partner_id.commercial_partner_id
            )
            if candidates:
                (candidates | payment_line).reconcile()
