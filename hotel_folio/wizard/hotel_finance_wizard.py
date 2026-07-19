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


class HotelRegisterPaymentWizard(models.TransientModel):
    _name = "hotel.register.payment.wizard"
    _description = "Register Hotel Deposit or Agency Advance"

    folio_id = fields.Many2one("hotel.folio", required=True, readonly=True)
    payment_purpose = fields.Selection(
        [
            ("guest_deposit", "Guest Deposit"),
            ("agency_advance", "Agency Advance"),
        ],
        string="Purpose",
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Received From", required=True, readonly=True
    )
    property_id = fields.Many2one(
        related="folio_id.property_id", string="Property", readonly=True
    )
    company_id = fields.Many2one(
        related="property_id.company_id", string="Company", readonly=True
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Payment Journal",
        required=True,
        readonly=True,
        check_company=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
    )
    currency_id = fields.Many2one(
        related="folio_id.currency_id", string="Currency", readonly=True
    )
    amount = fields.Monetary(required=True, currency_field="currency_id")
    payment_date = fields.Date(
        string="Payment Date", required=True, default=fields.Date.context_today
    )
    payment_reference = fields.Char(string="Payment Reference")

    @api.constrains("amount")
    def _check_amount(self):
        if any(wizard.amount <= 0 for wizard in self):
            raise ValidationError(_("The payment amount must be greater than zero."))

    def _check_registration_role(self):
        allowed = any(
            self.env.user.has_group(group)
            for group in (
                "hotel_base.group_hotel_frontdesk",
                "hotel_base.group_hotel_accountant",
                "hotel_base.group_hotel_manager",
            )
        )
        if not allowed:
            raise UserError(
                _(
                    "Only Front Desk, Hotel Accountant, or Manager users can "
                    "register hotel deposits and advances."
                )
            )

    def action_register(self):
        self.ensure_one()
        self._check_registration_role()
        expected = self.folio_id._payment_registration_defaults(
            self.payment_purpose
        )
        if (
            self.folio_id.id != expected["folio_id"]
            or self.partner_id.id != expected["partner_id"]
            or self.journal_id.id != expected["journal_id"]
        ):
            raise UserError(
                _("The deposit or advance details no longer match the folio.")
            )
        payment = (
            self.env["account.payment"]
            .sudo()
            .with_company(self.company_id)
            .create(
                {
                    "company_id": self.company_id.id,
                    "amount": self.amount,
                    "date": self.payment_date,
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "partner_id": self.partner_id.id,
                    "currency_id": self.currency_id.id,
                    "journal_id": self.journal_id.id,
                    "memo": self.payment_reference or self.folio_id.name,
                    "payment_reference": self.payment_reference,
                    "hotel_property_id": self.property_id.id,
                    "hotel_folio_id": self.folio_id.id,
                    "hotel_payment_purpose": self.payment_purpose,
                }
            )
        )
        payment.action_post()
        purpose_label = dict(
            self._fields["payment_purpose"]._description_selection(self.env)
        )[self.payment_purpose]
        self.folio_id.message_post(
            body=_(
                "%(purpose)s %(payment)s for %(amount)s %(currency)s registered "
                "by %(user)s.",
                purpose=purpose_label,
                payment=payment.display_name,
                amount=self.amount,
                currency=self.currency_id.name,
                user=self.env.user.name,
            )
        )
        return {"type": "ir.actions.act_window_close"}


class HotelAddChargeWizard(models.TransientModel):
    _name = "hotel.add.charge.wizard"
    _description = "Add Hotel Folio Charge"

    folio_id = fields.Many2one("hotel.folio", required=True, readonly=True)
    product_id = fields.Many2one("product.product", required=True)
    quantity = fields.Float(default=1.0, required=True)
    price_unit = fields.Monetary(
        string="Unit Price", required=True, currency_field="currency_id"
    )
    discount = fields.Float(string="Discount (%)", default=0.0)
    tax_ids = fields.Many2many(
        "account.tax",
        string="Taxes",
        domain="[('company_id', '=', company_id), ('type_tax_use', 'in', ('sale', 'none'))]",
    )
    charge_date = fields.Datetime(
        string="Charge Date", required=True, default=fields.Datetime.now
    )
    override_reason = fields.Text(
        string="Supervisor Override Reason",
        help="Explain why this restricted charge is approved.",
    )
    property_id = fields.Many2one(
        related="folio_id.property_id", string="Property", readonly=True
    )
    company_id = fields.Many2one(
        related="property_id.company_id", string="Company", readonly=True
    )
    currency_id = fields.Many2one(
        related="folio_id.currency_id", string="Currency", readonly=True
    )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        for wizard in self.filtered("product_id"):
            wizard.price_unit = wizard.product_id.list_price
            wizard.tax_ids = wizard.product_id.taxes_id.filtered(
                lambda tax: tax.company_id == wizard.company_id
            )

    @api.constrains("quantity", "price_unit", "discount")
    def _check_charge_values(self):
        for wizard in self:
            if wizard.quantity <= 0:
                raise ValidationError(_("Charge quantity must be greater than zero."))
            if wizard.price_unit < 0:
                raise ValidationError(_("Charge unit price cannot be negative."))
            if not 0 <= wizard.discount <= 100:
                raise ValidationError(_("Discount must be between 0 and 100 percent."))

    def _check_add_charge_role(self):
        allowed = any(
            self.env.user.has_group(group)
            for group in (
                "hotel_base.group_hotel_frontdesk",
                "hotel_base.group_hotel_accountant",
                "hotel_base.group_hotel_manager",
            )
        )
        if not allowed:
            raise UserError(
                _(
                    "Only Front Desk, Hotel Accountant, or Manager users can "
                    "add folio charges."
                )
            )

    def action_add_charge(self):
        self.ensure_one()
        self._check_add_charge_role()
        if not self.folio_id.is_open:
            raise UserError(_("Only an open folio can receive a charge."))
        reason = (self.override_reason or "").strip()
        if reason and not self.env.user.has_group(
            "hotel_base.group_hotel_fo_supervisor"
        ):
            raise UserError(
                _("Only a Front Office Supervisor can enter an override reason.")
            )
        self.folio_id.with_context(service_override_reason=reason).add_charge(
            self.product_id,
            qty=self.quantity,
            price_unit=self.price_unit,
            date=self.charge_date,
            discount=self.discount,
            tax_ids=self.tax_ids.ids,
        )
        return {"type": "ir.actions.act_window_close"}
