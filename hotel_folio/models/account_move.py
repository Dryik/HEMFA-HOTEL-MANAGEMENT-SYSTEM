from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    hotel_property_id = fields.Many2one(
        "hotel.property", string="Hotel Property", index=True, copy=False
    )
    hotel_folio_id = fields.Many2one(
        "hotel.folio", string="Hotel Folio", index=True, copy=False
    )
    hotel_reservation_group_id = fields.Many2one(
        "hotel.reservation.group", string="Hotel Group Reservation", index=True, copy=False
    )
    hotel_manual_fx_reason = fields.Text(readonly=True, copy=False)
    hotel_manual_fx_user_id = fields.Many2one(
        "res.users", string="FX Approved By", readonly=True, copy=False
    )
    hotel_manual_fx_at = fields.Datetime(readonly=True, copy=False)

    @api.constrains(
        "company_id", "hotel_property_id", "hotel_folio_id", "hotel_reservation_group_id"
    )
    def _check_hotel_company_consistency(self):
        for move in self:
            if move.hotel_property_id and move.hotel_property_id.company_id != move.company_id:
                raise ValidationError(
                    _("The hotel property and accounting document must use the same company.")
                )
            if move.hotel_folio_id and move.hotel_folio_id.property_id != move.hotel_property_id:
                raise ValidationError(
                    _("The hotel folio must belong to the accounting document property.")
                )
            if (
                move.hotel_reservation_group_id
                and move.hotel_reservation_group_id.property_id != move.hotel_property_id
            ):
                raise ValidationError(
                    _("The group reservation must belong to the accounting document property.")
                )

    def action_open_hotel_manual_fx(self):
        self.ensure_one()
        if self.state != "draft" or not self.is_invoice(include_receipts=True):
            raise UserError(_("Manual FX can only be changed on a draft invoice."))
        return {
            "name": _("Approve Manual FX Rate"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.manual.fx.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_move_id": self.id,
                "default_new_rate": self.invoice_currency_rate,
            },
        }

    def _apply_hotel_manual_fx(self, new_rate, reason):
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_accountant"):
            raise UserError(_("Only a Hotel Accountant or Manager can approve manual FX."))
        if (
            not self.hotel_property_id
            or self.state != "draft"
            or not self.is_invoice(include_receipts=True)
        ):
            raise UserError(_("Manual FX can only be changed on a draft hotel invoice."))
        if new_rate <= 0:
            raise UserError(_("The currency rate must be greater than zero."))
        reason = (reason or "").strip()
        if not reason:
            raise UserError(_("A reason is required for a manual FX change."))
        old_rate = self.invoice_currency_rate
        rate_move = self.with_context(check_move_validity=False)
        super(AccountMove, rate_move).write({"invoice_currency_rate": new_rate})
        self._recompute_hotel_manual_fx_balances(new_rate)
        super(AccountMove, self).write(
            {
                "hotel_manual_fx_reason": reason,
                "hotel_manual_fx_user_id": self.env.user.id,
                "hotel_manual_fx_at": fields.Datetime.now(),
            }
        )
        self.message_post(
            body=_(
                "Manual FX approved by %(user)s: %(old)s → %(new)s. Reason: %(reason)s",
                user=self.env.user.name,
                old=old_rate,
                new=new_rate,
                reason=reason,
            )
        )
        return True

    def _recompute_hotel_manual_fx_balances(self, new_rate):
        """Revalue a draft invoice and absorb only conversion rounding."""
        self.ensure_one()
        currency = self.company_currency_id
        converted_lines = self.line_ids.filtered(
            lambda line: line.currency_id == self.currency_id
            and line.display_type
            not in ("line_section", "line_subsection", "line_note")
        )
        payment_terms = converted_lines.filtered(
            lambda line: line.display_type == "payment_term"
            or line.account_id.account_type
            in ("asset_receivable", "liability_payable")
        ).sorted(lambda line: (line.date_maturity or self.date, line.id))
        if not converted_lines or not payment_terms:
            raise UserError(_("The entry is not balanced."))

        line_context = {
            "check_move_validity": False,
            "skip_invoice_sync": True,
        }
        for line in converted_lines:
            line.with_context(**line_context).write(
                {"balance": currency.round(line.amount_currency / new_rate)}
            )

        self.line_ids.flush_recordset(["balance"])
        imbalance = currency.round(sum(self.line_ids.mapped("balance")))
        maximum_rounding = currency.rounding * max(len(converted_lines), 1)
        if abs(imbalance) > maximum_rounding:
            raise UserError(_("The entry is not balanced."))
        if not currency.is_zero(imbalance):
            balancing_line = payment_terms[-1]
            balancing_line.with_context(**line_context).write(
                {"balance": balancing_line.balance - imbalance}
            )
        self.line_ids.flush_recordset(["balance"])
        if self._get_unbalanced_moves({"records": self}):
            raise UserError(_("The entry is not balanced."))
        return True

    def write(self, vals):
        if self.env.su and self.env.context.get("hotel_migration"):
            return super().write(vals)
        controlled = {
            "hotel_property_id",
            "hotel_folio_id",
            "hotel_reservation_group_id",
            "hotel_manual_fx_reason",
            "hotel_manual_fx_user_id",
            "hotel_manual_fx_at",
        }
        if controlled.intersection(vals):
            raise UserError(
                _("Hotel accounting references can only be changed by their workflows.")
            )
        if "invoice_currency_rate" in vals and self.filtered("hotel_property_id"):
            raise UserError(_("Use the approved Hotel Manual FX wizard to change this rate."))
        return super().write(vals)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    hotel_property_id = fields.Many2one(
        "hotel.property", string="Hotel Property", index=True, copy=False
    )
    hotel_folio_id = fields.Many2one(
        "hotel.folio", string="Hotel Folio", index=True, copy=False
    )
    hotel_payment_purpose = fields.Selection(
        [
            ("standard", "Standard"),
            ("guest_deposit", "Guest Deposit"),
            ("agency_advance", "Agency Advance"),
            ("folio_settlement", "Folio Settlement"),
            ("refund", "Guest Refund"),
            ("payout", "Cash Payout"),
        ],
        default="standard",
        required=True,
        index=True,
        copy=False,
    )
    hotel_available_advance = fields.Monetary(
        string="Available Advance",
        compute="_compute_hotel_available_advance",
        currency_field="currency_id",
    )

    @api.onchange("hotel_payment_purpose", "company_id")
    def _onchange_hotel_payment_company(self):
        for payment in self:
            if payment.hotel_payment_purpose == "standard":
                payment.hotel_property_id = False
            else:
                company = payment.company_id or self.env.company
                payment.hotel_property_id = self.env["hotel.property"].with_company(
                    company
                )._get_default_property()

    @api.depends(
        "state",
        "move_id.line_ids.amount_residual",
        "move_id.line_ids.amount_residual_currency",
        "move_id.line_ids.account_id.account_type",
    )
    def _compute_hotel_available_advance(self):
        for payment in self:
            if payment.hotel_payment_purpose not in ("guest_deposit", "agency_advance"):
                payment.hotel_available_advance = 0.0
                continue
            receivable_lines = payment.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
            )
            if payment.currency_id == payment.company_currency_id:
                payment.hotel_available_advance = sum(
                    abs(line.amount_residual) for line in receivable_lines
                )
            else:
                payment.hotel_available_advance = sum(
                    abs(line.amount_residual_currency) for line in receivable_lines
                )

    def _generate_move_vals(
        self, write_off_line_vals=None, force_balance=None, line_ids=None
    ):
        values = super()._generate_move_vals(
            write_off_line_vals=write_off_line_vals,
            force_balance=force_balance,
            line_ids=line_ids,
        )
        values.update(
            {
                "hotel_property_id": self.hotel_property_id.id,
                "hotel_folio_id": self.hotel_folio_id.id,
            }
        )
        return values

    def _assign_hotel_folio(self, folio):
        self.ensure_one()
        folio.ensure_one()
        if self.hotel_folio_id and self.hotel_folio_id != folio:
            raise UserError(_("This payment is already allocated to another folio."))
        if self.hotel_property_id != folio.property_id:
            raise UserError(_("The payment and folio must use the same property."))
        payees = folio.line_ids.mapped("payee_partner_id")
        payees |= folio.partner_id | folio.agency_id
        if self.partner_id and self.partner_id not in payees:
            raise UserError(_("The payment partner is not a guest or routed payee on this folio."))
        return super(AccountPayment, self).write({"hotel_folio_id": folio.id})

    def write(self, vals):
        controlled = {
            "hotel_property_id",
            "hotel_folio_id",
            "hotel_payment_purpose",
        }
        if controlled.intersection(vals) and self.filtered(
            lambda payment: payment.state != "draft"
        ):
            raise UserError(_("Posted hotel payment references are immutable."))
        return super().write(vals)

    @api.constrains(
        "company_id", "partner_id", "hotel_property_id", "hotel_folio_id", "hotel_payment_purpose"
    )
    def _check_hotel_payment_consistency(self):
        for payment in self:
            if payment.hotel_payment_purpose != "standard" and not payment.hotel_property_id:
                raise ValidationError(_("The active company is required for hotel payments."))
            if payment.hotel_payment_purpose in (
                "guest_deposit",
                "agency_advance",
                "folio_settlement",
            ) and payment.payment_type != "inbound":
                raise ValidationError(
                    _("Deposits, advances, and settlements must be inbound payments.")
                )
            if payment.hotel_payment_purpose in ("refund", "payout") and (
                payment.payment_type != "outbound"
            ):
                raise ValidationError(_("Refunds and payouts must be outbound payments."))
            if payment.hotel_payment_purpose in (
                "folio_settlement",
                "refund",
            ) and not payment.hotel_folio_id:
                raise ValidationError(_("Folio settlements and refunds require a folio."))
            if (
                payment.hotel_payment_purpose == "guest_deposit"
                and not payment.partner_id.is_hotel_guest
            ):
                raise ValidationError(_("A guest deposit requires a hotel guest."))
            if (
                payment.hotel_payment_purpose == "agency_advance"
                and not payment.partner_id.is_hotel_agency
            ):
                raise ValidationError(_("An agency advance requires an agency or entity."))
            if (
                payment.hotel_property_id
                and payment.hotel_property_id.company_id != payment.company_id
            ):
                raise ValidationError(_("The hotel payment must use its active company."))
            if payment.hotel_folio_id:
                if payment.hotel_folio_id.property_id != payment.hotel_property_id:
                    raise ValidationError(_("The payment folio must belong to the active company."))
                payees = payment.hotel_folio_id.line_ids.mapped("payee_partner_id")
                payees |= payment.hotel_folio_id.partner_id | payment.hotel_folio_id.agency_id
                if payment.partner_id and payment.partner_id not in payees:
                    raise ValidationError(
                        _("The payment partner is not a guest or routed payee on this folio.")
                    )


class HotelProperty(models.Model):
    _inherit = "hotel.property"

    room_charge_clearing_account_id = fields.Many2one(
        "account.account",
        string="Room-charge Clearing Account",
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
    )
    room_charge_journal_id = fields.Many2one(
        "account.journal",
        string="Room-charge Transfer Journal",
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        check_company=True,
    )
    deposit_journal_id = fields.Many2one(
        "account.journal",
        string="Guest Deposit Journal",
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
        check_company=True,
    )
    advance_journal_id = fields.Many2one(
        "account.journal",
        string="Agency Advance Journal",
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
        check_company=True,
    )
    cancellation_fee_product_id = fields.Many2one(
        "product.product",
        string="Cancellation Fee Product",
        domain=[("type", "=", "service")],
    )
    no_show_fee_product_id = fields.Many2one(
        "product.product",
        string="No-show Fee Product",
        domain=[("type", "=", "service")],
    )

    @api.constrains(
        "company_id",
        "room_charge_clearing_account_id",
        "room_charge_journal_id",
        "deposit_journal_id",
        "advance_journal_id",
    )
    def _check_finance_configuration_company(self):
        for prop in self:
            account = prop.room_charge_clearing_account_id
            if account and (
                prop.company_id not in account.company_ids
                or account.account_type != "asset_receivable"
                or not account.reconcile
            ):
                raise ValidationError(
                    _(
                        "The room-charge clearing account must be a reconcilable "
                        "receivable account available to the property company."
                    )
                )
            journals = (
                prop.room_charge_journal_id
                | prop.deposit_journal_id
                | prop.advance_journal_id
            )
            if journals.filtered(lambda journal: journal.company_id != prop.company_id):
                raise ValidationError(
                    _("Every hotel finance journal must belong to the property company.")
                )


class ResCompany(models.Model):
    _inherit = "res.company"

    hotel_room_charge_clearing_account_id = fields.Many2one(
        string="Room-charge Clearing Account",
        related="hotel_property_config_id.room_charge_clearing_account_id",
        domain="[('company_ids', 'in', [id]), ('account_type', '=', 'asset_receivable'), ('reconcile', '=', True)]",
        readonly=False,
    )
    hotel_room_charge_journal_id = fields.Many2one(
        string="Room-charge Transfer Journal",
        related="hotel_property_config_id.room_charge_journal_id",
        domain="[('company_id', '=', id), ('type', '=', 'general')]",
        readonly=False,
    )
    hotel_deposit_journal_id = fields.Many2one(
        string="Guest Deposit Journal",
        related="hotel_property_config_id.deposit_journal_id",
        domain="[('company_id', '=', id), ('type', 'in', ('bank', 'cash'))]",
        readonly=False,
    )
    hotel_advance_journal_id = fields.Many2one(
        string="Agency Advance Journal",
        related="hotel_property_config_id.advance_journal_id",
        domain="[('company_id', '=', id), ('type', 'in', ('bank', 'cash'))]",
        readonly=False,
    )
    hotel_cancellation_fee_product_id = fields.Many2one(
        string="Cancellation Fee Product",
        related="hotel_property_config_id.cancellation_fee_product_id",
        domain="[('type', '=', 'service'), '|', ('company_id', '=', False), ('company_id', '=', id)]",
        readonly=False,
    )
    hotel_no_show_fee_product_id = fields.Many2one(
        string="No-show Fee Product",
        related="hotel_property_config_id.no_show_fee_product_id",
        domain="[('type', '=', 'service'), '|', ('company_id', '=', False), ('company_id', '=', id)]",
        readonly=False,
    )
