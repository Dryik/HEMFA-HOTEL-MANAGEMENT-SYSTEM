from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class HotelFolio(models.Model):
    _name = "hotel.folio"
    _description = "Hotel Folio Ledger"
    _inherit = ["mail.thread"]

    name = fields.Char(
        string="Folio Number",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
    )
    reservation_id = fields.Many2one(
        "hotel.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="reservation_id.partner_id",
        store=True,
        readonly=True,
        string="Guest",
    )
    agency_id = fields.Many2one(
        "res.partner",
        related="reservation_id.agency_id",
        store=True,
        readonly=True,
        string="Agency / Entity",
    )
    property_id = fields.Many2one(
        related="reservation_id.property_id",
        store=True,
        readonly=True,
        string="Property",
    )
    reservation_state = fields.Selection(
        related="reservation_id.state",
        store=True,
        readonly=True,
        string="Stay Status",
    )
    line_ids = fields.One2many(
        "hotel.folio.line", "folio_id", string="Folio Lines"
    )
    invoice_ids = fields.Many2many(
        "account.move",
        "hotel_folio_invoice_rel",
        "folio_id",
        "invoice_id",
        string="Invoices",
        readonly=True,
    )
    payment_ids = fields.One2many(
        "account.payment",
        "hotel_folio_id",
        string="Payments / Advances",
        readonly=True,
    )
    amount_total = fields.Monetary(
        string="Total Charges", compute="_compute_totals", store=True
    )
    amount_untaxed = fields.Monetary(
        string="Untaxed", compute="_compute_totals", store=True
    )
    amount_tax = fields.Monetary(
        string="Tax", compute="_compute_totals", store=True
    )
    amount_invoiced = fields.Monetary(
        string="Invoiced / Transferred", compute="_compute_totals", store=True
    )
    amount_paid = fields.Monetary(
        string="Amount Paid", compute="_compute_totals", store=True
    )
    amount_due = fields.Monetary(
        string="Amount Due", compute="_compute_totals", store=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="reservation_id.currency_id",
        store=True,
        readonly=True,
    )
    is_open = fields.Boolean(
        string="Open",
        compute="_compute_is_open",
        store=True,
        help="Open while the stay is active or the folio still has a balance due.",
    )

    @api.depends(
        "line_ids.amount_untaxed",
        "line_ids.amount_tax",
        "line_ids.amount_total",
        "line_ids.invoice_line_id.move_id.state",
        "line_ids.invoice_line_id.move_id.line_ids.amount_residual",
        "line_ids.invoice_line_id.move_id.line_ids.amount_residual_currency",
        "line_ids.accounting_move_id.state",
        "line_ids.accounting_move_id.line_ids.amount_residual",
        "line_ids.accounting_move_id.line_ids.amount_residual_currency",
        "invoice_ids.state",
        "payment_ids.move_id.state",
        "payment_ids.move_id.line_ids.amount_residual",
        "payment_ids.move_id.line_ids.amount_residual_currency",
    )
    def _compute_totals(self):
        document_line_by_folio = defaultdict(lambda: self.env["hotel.folio.line"])
        document_moves = self.env["account.move"]
        for folio in self:
            for line in folio.line_ids:
                move = line.invoice_line_id.move_id or line.accounting_move_id
                if move.state == "posted":
                    document_moves |= move
                    document_line_by_folio[(folio.id, move.id)] |= line

        # A group invoice can contain lines from several folios.  Allocate its
        # native receivable residual proportionally instead of counting the
        # complete invoice residual on every member folio.
        all_document_lines = self.env["hotel.folio.line"]
        if document_moves:
            all_document_lines = self.env["hotel.folio.line"].search(
                [
                    "|",
                    ("invoice_line_id.move_id", "in", document_moves.ids),
                    ("accounting_move_id", "in", document_moves.ids),
                ]
            )
        move_hotel_totals = defaultdict(float)
        for line in all_document_lines:
            move = line.invoice_line_id.move_id or line.accounting_move_id
            if move in document_moves:
                move_hotel_totals[move.id] += line.amount_total

        residual_cache = {}
        for folio in self:
            currency = folio._effective_currency()
            folio.amount_untaxed = sum(folio.line_ids.mapped("amount_untaxed"))
            folio.amount_tax = sum(folio.line_ids.mapped("amount_tax"))
            folio.amount_total = sum(folio.line_ids.mapped("amount_total"))
            transferred_lines = self.env["hotel.folio.line"]
            receivable_residual = 0.0
            for move in document_moves:
                folio_move_lines = document_line_by_folio[(folio.id, move.id)]
                if not folio_move_lines:
                    continue
                transferred_lines |= folio_move_lines
                cache_key = (move.id, currency.id)
                if cache_key not in residual_cache:
                    residual_cache[cache_key] = folio._receivable_residual_in_currency(
                        move
                    )
                move_total = move_hotel_totals[move.id]
                folio_share = sum(folio_move_lines.mapped("amount_total"))
                if float_is_zero(
                    move_total,
                    precision_rounding=currency.rounding or 0.01,
                ):
                    # A zero-value document has no amount to allocate.
                    continue
                receivable_residual += (
                    residual_cache[cache_key] * folio_share / move_total
                )

            folio.amount_invoiced = sum(transferred_lines.mapped("amount_total"))
            posted_payment_moves = folio.payment_ids.mapped("move_id").filtered(
                lambda move: move.state == "posted" and move not in document_moves
            )
            for move in posted_payment_moves:
                cache_key = (move.id, currency.id)
                if cache_key not in residual_cache:
                    residual_cache[cache_key] = folio._receivable_residual_in_currency(
                        move
                    )
                receivable_residual += residual_cache[cache_key]

            uninvoiced = folio.amount_total - folio.amount_invoiced
            folio.amount_due = currency.round(uninvoiced + receivable_residual)
            folio.amount_paid = currency.round(folio.amount_total - folio.amount_due)

    def _effective_currency(self):
        """Return a currency even while a new folio has no reservation yet."""
        self.ensure_one()
        return (
            self.currency_id
            or self.property_id.company_id.currency_id
            or self.env.company.currency_id
        )

    def _receivable_residual_in_currency(self, move):
        """Return a posted move's signed receivable residual in folio currency."""
        self.ensure_one()
        target_currency = self._effective_currency()
        total = 0.0
        receivable_lines = move.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        for line in receivable_lines:
            if line.currency_id == target_currency:
                total += line.amount_residual_currency
            elif line.company_currency_id == target_currency:
                total += line.amount_residual
            else:
                total += line.company_currency_id._convert(
                    line.amount_residual,
                    target_currency,
                    line.company_id,
                    line.date or move.date,
                )
        return target_currency.round(total)

    @api.depends("reservation_id.state", "amount_due", "currency_id")
    def _compute_is_open(self):
        closed_states = ("checked_out", "cancelled", "no_show")
        for folio in self:
            res_closed = folio.reservation_id.state in closed_states
            precision = folio.currency_id.rounding if folio.currency_id else 0.01
            settled = float_is_zero(folio.amount_due, precision_rounding=precision)
            # Closed only when the stay is finished and nothing is due.
            folio.is_open = not (res_closed and settled)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get("name") not in (None, False, _("New")):
                raise UserError(_("Folio references are assigned by the hotel workflow."))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.folio")
                    or _("New")
                )
        return super().create(vals_list)

    def _link_account_move(self, move):
        self.ensure_one()
        move.ensure_one()
        group = move.hotel_reservation_group_id
        valid_group_link = bool(group and self.reservation_id.group_id == group)
        if (
            move.hotel_property_id != self.property_id
            or (move.hotel_folio_id and move.hotel_folio_id != self)
            or not (move.hotel_folio_id == self or valid_group_link)
        ):
            raise UserError(_("The accounting document does not belong to this folio."))
        return super(HotelFolio, self).write(
            {"invoice_ids": [Command.link(move.id)]}
        )

    def write(self, vals):
        if self.env.su and self.env.context.get("hotel_migration"):
            return super().write(vals)
        if "name" in vals or "invoice_ids" in vals:
            raise UserError(
                _("Folio identity and accounting links can only be changed by their workflows.")
            )
        if "reservation_id" in vals and self.filtered(
            lambda folio: folio.line_ids or folio.invoice_ids or folio.payment_ids
        ):
            raise UserError(_("A folio with financial activity cannot be reassigned."))
        return super().write(vals)

    def add_charge(
        self,
        product,
        qty=1.0,
        price_unit=None,
        date=None,
        discount=0.0,
        tax_ids=None,
        source_type="manual",
        source_reference=None,
        source_key=None,
        invoiceable=True,
    ):
        if (
            source_type != "manual"
            or source_reference
            or source_key
            or not invoiceable
        ):
            raise UserError(
                _("Operational charge sources can only be assigned by their hotel workflows.")
            )
        return self._add_charge_impl(
            product,
            qty=qty,
            price_unit=price_unit,
            date=date,
            discount=discount,
            tax_ids=tax_ids,
        )

    def _add_workflow_charge(
        self,
        product,
        qty=1.0,
        price_unit=None,
        date=None,
        discount=0.0,
        tax_ids=None,
        source_type=None,
        source_reference=None,
        source_key=None,
        invoiceable=True,
        payee=None,
    ):
        if source_type not in {
            "room_night",
            "pos",
            "service",
            "amendment",
            "stay_policy",
            "reversal",
            "migration",
        } or not source_key:
            raise UserError(_("A valid immutable workflow source is required."))
        return self._add_charge_impl(
            product,
            qty=qty,
            price_unit=price_unit,
            date=date,
            discount=discount,
            tax_ids=tax_ids,
            source_type=source_type,
            source_reference=source_reference,
            source_key=source_key,
            invoiceable=invoiceable,
            payee=payee,
            workflow=True,
        )

    def _add_charge_impl(
        self,
        product,
        qty=1.0,
        price_unit=None,
        date=None,
        discount=0.0,
        tax_ids=None,
        source_type="manual",
        source_reference=None,
        source_key=None,
        invoiceable=True,
        payee=None,
        workflow=False,
    ):
        self.ensure_one()
        if price_unit is None:
            price_unit = product.list_price

        payee = self._get_charge_payee(product, payee=payee)

        # Determine taxes
        company = self.property_id.company_id
        taxes = (
            self.env["account.tax"].browse(tax_ids).exists()
            if tax_ids is not None
            else product.taxes_id.filtered(lambda tax: tax.company_id == company)
        )

        charge_datetime = date or fields.Datetime.now()
        values = {
            "folio_id": self.id,
            "product_id": product.id,
            "name": product.display_name or product.name,
            "qty": qty,
            "price_unit": price_unit,
            "discount": discount,
            "payee_partner_id": payee.id,
            "date": charge_datetime,
            "service_date": self.property_id.get_business_date(charge_datetime),
            "tax_ids": [(6, 0, taxes.ids)],
            "source_type": source_type,
            "source_reference": source_reference,
            "source_key": source_key,
            "invoiceable": invoiceable,
        }
        line_model = self.env["hotel.folio.line"]
        line = (
            line_model._create_workflow_charge(values)
            if workflow
            else line_model._create_manual_charge(values)
        )
        return line

    def _get_charge_payee(self, product, payee=None):
        """Resolve the routed payee without creating a folio line."""
        self.ensure_one()
        if payee:
            return payee
        payee = self.partner_id
        if self.reservation_id.agency_id:
            rule = self.env["hotel.folio.routing.rule"].search(
                [
                    ("property_id", "=", self.reservation_id.property_id.id),
                    ("category_id", "=", product.categ_id.id),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if rule and rule.routing_type == "agency":
                payee = rule.agency_id or self.reservation_id.agency_id
        return payee

    def action_create_invoice(self, partner_id=None):
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_accountant"):
            raise UserError(_("Only a Hotel Accountant or Manager can create hotel invoices."))
        partner_id = partner_id or self.env.context.get("partner_id") or self.partner_id
        if isinstance(partner_id, int):
            partner_id = self.env["res.partner"].browse(partner_id).exists()
        if not partner_id:
            raise UserError(_("Select a valid guest or routed payee."))

        # Find uninvoiced lines for this payee partner
        lines_to_invoice = self.line_ids.filtered(
            lambda line: (
                line.payee_partner_id == partner_id
                and line.invoiceable
                and not line.invoice_line_id
                and not line.accounting_move_id
            )
        )
        if not lines_to_invoice:
            raise UserError(_("No uninvoiced lines found for this payee."))

        # Create account.move
        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": partner_id.id,
            "currency_id": self.currency_id.id,
            "company_id": self.reservation_id.property_id.company_id.id or self.env.company.id,
            "hotel_property_id": self.property_id.id,
            "hotel_folio_id": self.id,
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "name": line.name,
                        "quantity": line.qty,
                        "price_unit": line.price_unit,
                        "discount": line.discount,
                        "tax_ids": [(6, 0, line.tax_ids.ids)],
                    },
                )
                for line in lines_to_invoice
            ],
        }
        invoice = self.env["account.move"].create(invoice_vals)
        self._link_account_move(invoice)

        # Link folio lines to invoice lines
        for line, inv_line in zip(lines_to_invoice, invoice.invoice_line_ids):
            line._link_invoice_line(inv_line)

        return {
            "name": _("Invoice"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": invoice.id,
            "target": "current",
        }

    def action_open_allocate_advance(self):
        self.ensure_one()
        posted_open_invoices = self.invoice_ids.filtered(
            lambda move: move.state == "posted"
            and move.payment_state in ("not_paid", "partial", "in_payment")
        )
        if not posted_open_invoices:
            raise UserError(_("Post an open folio invoice before allocating an advance."))
        return {
            "name": _("Allocate Deposit / Advance"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.allocate.advance.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_folio_id": self.id,
                "default_invoice_id": posted_open_invoices[:1].id,
            },
        }

    def _payment_registration_defaults(self, purpose):
        self.ensure_one()
        if not self.is_open:
            raise UserError(
                _("Only an open folio can receive a deposit or advance.")
            )
        company = self.property_id.company_id
        if purpose == "guest_deposit":
            partner = self.partner_id
            journal = company.hotel_deposit_journal_id
            if not journal:
                raise UserError(
                    _(
                        "Configure a Guest Deposit Journal before registering "
                        "deposits."
                    )
                )
        elif purpose == "agency_advance":
            partner = self.agency_id
            if not partner:
                raise UserError(
                    _(
                        "Select an agency or entity on the folio before "
                        "registering an advance."
                    )
                )
            journal = company.hotel_advance_journal_id
            if not journal:
                raise UserError(
                    _(
                        "Configure an Agency Advance Journal before registering "
                        "advances."
                    )
                )
        else:
            raise UserError(_("Unsupported hotel payment purpose."))
        return {
            "folio_id": self.id,
            "payment_purpose": purpose,
            "partner_id": partner.id,
            "journal_id": journal.id,
        }

    def _open_payment_registration(self, purpose, title):
        self.ensure_one()
        defaults = self._payment_registration_defaults(purpose)
        return {
            "name": title,
            "type": "ir.actions.act_window",
            "res_model": "hotel.register.payment.wizard",
            "views": [
                (
                    self.env.ref(
                        "hotel_folio.hotel_register_payment_wizard_view_form"
                    ).id,
                    "form",
                )
            ],
            "view_mode": "form",
            "target": "new",
            "context": {
                f"default_{field_name}": value
                for field_name, value in defaults.items()
            },
        }

    def action_open_register_deposit(self):
        return self._open_payment_registration(
            "guest_deposit", _("Register Deposit")
        )

    def action_open_register_advance(self):
        return self._open_payment_registration(
            "agency_advance", _("Register Advance")
        )

    def action_open_add_charge(self):
        self.ensure_one()
        if not self.is_open:
            raise UserError(_("Only an open folio can receive a charge."))
        return {
            "name": _("Add Charge"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.add.charge.wizard",
            "views": [
                (
                    self.env.ref(
                        "hotel_folio.hotel_add_charge_wizard_view_form"
                    ).id,
                    "form",
                )
            ],
            "view_mode": "form",
            "target": "new",
            "context": {"default_folio_id": self.id},
        }

    def unlink(self):
        for folio in self:
            if any(
                line.is_posted or line.source_type != "manual"
                for line in folio.line_ids
            ):
                raise UserError(
                    _(
                        "You cannot delete a folio with workflow-generated, "
                        "posted, or invoiced charges."
                    )
                )
        return super().unlink()


class HotelFolioLine(models.Model):
    _name = "hotel.folio.line"
    _description = "Hotel Folio Line"
    _order = "date, id"

    folio_id = fields.Many2one(
        "hotel.folio", string="Folio", required=True, ondelete="cascade"
    )
    date = fields.Datetime(
        string="Date", required=True, default=lambda self: fields.Datetime.now()
    )
    product_id = fields.Many2one(
        "product.product", string="Product", required=True
    )
    name = fields.Char(string="Description", required=True)
    qty = fields.Float(string="Quantity", default=1.0, required=True)
    price_unit = fields.Monetary(
        string="Unit Price", required=True, currency_field="currency_id"
    )
    discount = fields.Float(string="Discount (%)", default=0.0)
    tax_ids = fields.Many2many("account.tax", string="Taxes")
    amount_untaxed = fields.Monetary(
        string="Untaxed", compute="_compute_amount", store=True,
        currency_field="currency_id",
    )
    amount_tax = fields.Monetary(
        string="Tax", compute="_compute_amount", store=True,
        currency_field="currency_id",
    )
    amount_total = fields.Monetary(
        string="Total", compute="_compute_amount", store=True,
        currency_field="currency_id",
    )
    amount = fields.Monetary(
        string="Amount (Deprecated)",
        compute="_compute_amount",
        store=True,
        currency_field="currency_id",
        help="Compatibility alias for Total; use amount_total in new integrations.",
    )
    service_date = fields.Date(required=True, default=fields.Date.today, index=True)
    source_type = fields.Selection(
        [
            ("manual", "Manual"),
            ("room_night", "Room Night"),
            ("pos", "POS"),
            ("amendment", "Reservation Amendment"),
            ("stay_policy", "Cancellation / No-show Policy"),
            ("reversal", "Reversal"),
            ("migration", "Migration"),
        ],
        required=True,
        default="manual",
        index=True,
    )
    source_reference = fields.Char(readonly=True, copy=False, index=True)
    source_key = fields.Char(readonly=True, copy=False, index=True)
    invoiceable = fields.Boolean(default=True)
    lock_state = fields.Selection(
        [
            ("unlocked", "Unlocked"),
            ("accounting", "Accounting"),
            ("pos", "POS"),
            ("reversal", "Reversal"),
        ],
        default="unlocked",
        required=True,
        readonly=True,
        copy=False,
    )
    payee_partner_id = fields.Many2one(
        "res.partner",
        string="Billed To",
        required=True,
        help="Entity responsible for this specific charge line.",
    )
    invoice_line_id = fields.Many2one(
        "account.move.line", string="Invoice Line", readonly=True, copy=False
    )
    accounting_move_id = fields.Many2one(
        "account.move", string="Accounting Transfer", readonly=True, copy=False
    )
    is_posted = fields.Boolean(
        string="Posted",
        default=False,
        help="If checked, the charge is locked by an accounting or operational workflow.",
    )
    reversal_of_id = fields.Many2one(
        "hotel.folio.line",
        string="Reversal Of",
        readonly=True,
        copy=False,
        ondelete="restrict",
    )
    reversal_line_ids = fields.One2many(
        "hotel.folio.line",
        "reversal_of_id",
        string="Reversal Lines",
        readonly=True,
    )
    reversal_reason = fields.Char(readonly=True, copy=False)
    reversed_by_id = fields.Many2one(
        "res.users", string="Reversed By", readonly=True, copy=False
    )
    reversed_at = fields.Datetime(readonly=True, copy=False)
    currency_id = fields.Many2one(
        "res.currency",
        related="folio_id.currency_id",
        store=True,
        readonly=True,
    )

    _source_key_uniq = models.Constraint(
        "unique (source_key)",
        "A financial source may create only one folio line.",
    )
    _discount_range = models.Constraint(
        "CHECK (discount >= 0 AND discount <= 100)",
        "Discount must be between 0 and 100 percent.",
    )

    @api.depends("qty", "price_unit", "discount", "tax_ids", "currency_id")
    def _compute_amount(self):
        for line in self:
            price = line.price_unit * (1.0 - line.discount / 100.0)
            taxes = line.tax_ids.compute_all(
                price,
                currency=line.currency_id,
                quantity=line.qty,
                product=line.product_id,
                partner=line.payee_partner_id,
            )
            line.amount_untaxed = taxes["total_excluded"]
            line.amount_tax = taxes["total_included"] - taxes["total_excluded"]
            line.amount_total = taxes["total_included"]
            line.amount = line.amount_total

    @api.constrains("folio_id", "tax_ids")
    def _check_tax_company(self):
        for line in self:
            company = line.folio_id.property_id.company_id
            if line.tax_ids.filtered(lambda tax: tax.company_id != company):
                raise ValidationError(
                    _("Folio taxes must belong to the hotel property company.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.su and self.env.context.get("hotel_migration"):
            return super().create(vals_list)
        action_fields = {
            "invoice_line_id",
            "accounting_move_id",
            "reversal_of_id",
            "reversal_reason",
            "reversed_by_id",
            "reversed_at",
            "amendment_id",
            "pos_order_id",
            "pos_order_line_id",
        }
        if any(
            vals.get("source_type", "manual") == "manual" for vals in vals_list
        ):
            raise UserError(
                _("Manual folio charges must be added with the Add Charge action.")
            )
        if not self.env.su:
            for vals in vals_list:
                if (
                    vals.get("is_posted")
                    or vals.get("lock_state") not in (None, False, "unlocked")
                    or action_fields.intersection(vals)
                    or vals.get("source_type", "manual") != "manual"
                    or vals.get("source_reference")
                    or vals.get("source_key")
                    or vals.get("invoiceable") is False
                ):
                    raise UserError(
                        _("Financial lock and source links can only be set by their hotel workflow.")
                    )
        return super().create(vals_list)

    @api.model
    def _create_manual_charge(self, values):
        if (
            values.get("source_type", "manual") != "manual"
            or values.get("source_reference")
            or values.get("source_key")
            or values.get("invoiceable") is False
            or values.get("is_posted")
            or values.get("lock_state") not in (None, False, "unlocked")
        ):
            raise UserError(_("A valid unlocked manual charge is required."))
        return super(HotelFolioLine, self).create(values)

    @api.model
    def _create_workflow_charge(self, values):
        if (
            values.get("source_type") in (None, "manual")
            or not values.get("source_key")
            or values.get("is_posted")
            or values.get("lock_state") not in (None, False, "unlocked")
        ):
            raise UserError(_("A valid unlocked workflow charge is required."))
        return super(HotelFolioLine, self).create(values)

    def write(self, vals):
        if self.env.su and self.env.context.get("hotel_migration"):
            return super().write(vals)
        always_immutable = {
            "folio_id",
            "source_type",
            "source_reference",
            "source_key",
        }
        if always_immutable.intersection(vals):
            raise UserError(_("Folio line source identity is immutable."))
        if "invoiceable" in vals and self.filtered(
            lambda line: line.source_type != "manual"
        ):
            raise UserError(_("Workflow-generated invoice eligibility is immutable."))
        action_controlled = {
            "is_posted",
            "lock_state",
            "invoice_line_id",
            "accounting_move_id",
            "reversal_of_id",
            "reversal_reason",
            "reversed_by_id",
            "reversed_at",
            "amendment_id",
            "pos_order_id",
            "pos_order_line_id",
        }
        if action_controlled.intersection(vals):
            raise UserError(
                _("Financial lock and source links can only be changed by their hotel workflow.")
            )
        workflow_financial_fields = {
            "name",
            "product_id",
            "qty",
            "price_unit",
            "discount",
            "tax_ids",
            "service_date",
            "payee_partner_id",
        }
        if workflow_financial_fields.intersection(vals) and self.filtered(
            lambda line: line.source_type != "manual"
        ):
            raise UserError(
                _(
                    "Workflow-generated folio charges are immutable. "
                    "Use the originating hotel workflow."
                )
            )
        protected_fields = {
            "date",
            "product_id",
            "name",
            "qty",
            "price_unit",
            "discount",
            "tax_ids",
            "service_date",
            "invoiceable",
            "is_posted",
            "lock_state",
            "payee_partner_id",
            "invoice_line_id",
            "accounting_move_id",
            "reversal_of_id",
            "reversal_reason",
            "reversed_by_id",
            "reversed_at",
            # Immutable source relations added by dependent hotel addons.
            "amendment_id",
            "pos_order_id",
            "pos_order_line_id",
        }
        locked = self.filtered(
            lambda line: line.is_posted
            or line.lock_state != "unlocked"
            or bool(line.invoice_line_id or line.accounting_move_id)
        )
        if locked and protected_fields.intersection(vals):
            raise UserError(
                _(
                    "Posted folio lines are immutable. Create a manager reversal "
                    "instead of editing the original charge."
                )
            )
        return super().write(vals)

    def _set_operational_lock(self, lock_state, accounting_move=None):
        """Lock an operationally posted line after validating its source."""
        self.ensure_one()
        if self.is_posted or self.lock_state != "unlocked":
            raise UserError(_("This folio line is already locked."))
        values = {"is_posted": True, "lock_state": lock_state}
        if lock_state == "pos":
            if (
                self.source_type != "pos"
                or not self.pos_order_line_id
                or not accounting_move
                or accounting_move.state != "posted"
                or accounting_move.move_type != "entry"
                or accounting_move.hotel_property_id != self.folio_id.property_id
                or accounting_move.hotel_folio_id != self.folio_id
            ):
                raise UserError(_("A POS lock requires its posted room-charge accounting transfer."))
            values["accounting_move_id"] = accounting_move.id
        else:
            raise UserError(_("Unsupported operational folio lock."))
        return super(HotelFolioLine, self).write(values)

    def _set_pos_source(self, order, order_line):
        self.ensure_one()
        order.ensure_one()
        order_line.ensure_one()
        if (
            self.is_posted
            or self.source_type != "pos"
            or order_line.order_id != order
            or order.config_id.hotel_property_id != self.folio_id.property_id
        ):
            raise UserError(_("The POS source does not match this folio charge."))
        return super(HotelFolioLine, self).write(
            {"pos_order_id": order.id, "pos_order_line_id": order_line.id}
        )

    def _set_amendment_source(self, amendment):
        self.ensure_one()
        amendment.ensure_one()
        if (
            self.is_posted
            or self.source_type != "amendment"
            or amendment.reservation_id != self.folio_id.reservation_id
        ):
            raise UserError(_("The amendment source does not match this folio charge."))
        return super(HotelFolioLine, self).write({"amendment_id": amendment.id})

    def _link_stay_reversal(self, original_line, reason):
        """Link an unlocked cancellation/no-show credit to its stay charge."""
        self.ensure_one()
        original_line.ensure_one()
        if (
            self.source_type != "reversal"
            or self.is_posted
            or self.folio_id != original_line.folio_id
            or original_line.source_type != "room_night"
            or self.qty >= 0
            or self.reversal_of_id
        ):
            raise UserError(_("The stay reversal does not match its original charge."))
        return super(HotelFolioLine, self).write(
            {
                "reversal_of_id": original_line.id,
                "reversal_reason": reason,
                "reversed_by_id": self.env.user.id,
                "reversed_at": fields.Datetime.now(),
            }
        )

    def _link_invoice_line(self, invoice_line):
        """Attach an immutable charge to its finance-generated draft invoice.

        This private method is the only valid transition from an operational
        charge to an accounting lock. It validates the generated invoice
        instead of trusting a caller-controlled context flag.
        """
        self.ensure_one()
        invoice_line.ensure_one()
        move = invoice_line.move_id
        if not (
            self.env.su
            or self.env.user.has_group("hotel_base.group_hotel_accountant")
        ):
            raise UserError(_("Only a Hotel Accountant or Manager can link hotel invoices."))
        if self.invoice_line_id or self.accounting_move_id:
            raise UserError(_("This folio line is already linked to accounting."))
        if move.state != "draft" or move.move_type != "out_invoice":
            raise UserError(_("Hotel charges can only be linked to a draft customer invoice."))
        if move.hotel_property_id != self.folio_id.property_id:
            raise UserError(_("The invoice and folio line must use the same hotel property."))
        if move.currency_id != self.currency_id:
            raise UserError(_("The invoice and folio line must use the same currency."))
        if invoice_line.product_id != self.product_id:
            raise UserError(_("The generated invoice product does not match the folio charge."))
        if self.currency_id.compare_amounts(
            invoice_line.price_total, self.amount_total
        ):
            raise UserError(_("The generated invoice total does not match the folio charge."))
        return super(HotelFolioLine, self).write(
            {
                "invoice_line_id": invoice_line.id,
                "is_posted": True,
                "lock_state": "accounting",
            }
        )

    def action_reverse(self, reason):
        """Create immutable negative lines; never mutate financial history."""
        if not self.env.user.has_group("hotel_base.group_hotel_manager"):
            raise UserError(_("Only a Hotel Manager can reverse a folio line."))
        if not reason or not reason.strip():
            raise UserError(_("A reversal reason is required."))

        reversals = self.env["hotel.folio.line"]
        for line in self:
            if not line.is_posted:
                raise UserError(_("Only posted folio lines can be reversed."))
            if line.reversal_of_id:
                raise UserError(_("A reversal line cannot be reversed again."))
            if line.reversal_line_ids:
                raise UserError(_("This folio line has already been reversed."))
            reversal = line._create_reversal_line(
                reason.strip()
            )
            line._create_accounting_reversal(reversal, reason.strip())
            line.folio_id.message_post(
                body=_(
                    "Charge %(line)s reversed by %(user)s. Reason: %(reason)s",
                    line=line.display_name,
                    user=self.env.user.name,
                    reason=reason.strip(),
                )
            )
            reversals |= reversal
        return reversals

    def action_open_reverse_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_manager"):
            raise UserError(_("Only a Hotel Manager can reverse a folio line."))
        return {
            "name": _("Reverse Folio Line"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.folio.line.reverse.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_folio_line_id": self.id},
        }

    def _create_reversal_line(self, reason):
        self.ensure_one()
        reversal_time = fields.Datetime.now()
        return super(HotelFolioLine, self).create(
                {
                    "folio_id": self.folio_id.id,
                    "date": reversal_time,
                    "product_id": self.product_id.id,
                    "name": _("Reversal of %(line)s: %(reason)s", line=self.name, reason=reason),
                    "qty": -self.qty,
                    "price_unit": self.price_unit,
                    "discount": self.discount,
                    "tax_ids": [(6, 0, self.tax_ids.ids)],
                    "payee_partner_id": self.payee_partner_id.id,
                    "is_posted": True,
                    "lock_state": "reversal",
                    "service_date": self.folio_id.property_id.get_business_date(
                        reversal_time
                    ),
                    "source_type": "reversal",
                    "source_reference": self.source_reference or self.display_name,
                    "source_key": f"reversal:{self.id}",
                    "invoiceable": self.invoiceable,
                    "reversal_of_id": self.id,
                    "reversal_reason": reason,
                    "reversed_by_id": self.env.user.id,
                    "reversed_at": fields.Datetime.now(),
                }
            )

    def _set_reversal_accounting_link(self, invoice_line=None, accounting_move=None):
        self.ensure_one()
        if not self.reversal_of_id or self.lock_state != "reversal":
            raise UserError(_("Only a workflow reversal can receive a reversal accounting link."))
        if bool(invoice_line) == bool(accounting_move):
            raise UserError(_("Provide exactly one reversal accounting document."))
        if invoice_line:
            invoice_line.ensure_one()
            move = invoice_line.move_id
            if (
                move.move_type != "out_refund"
                or move.hotel_property_id != self.folio_id.property_id
                or move.hotel_folio_id != self.folio_id
                or move.currency_id != self.currency_id
                or self.currency_id.compare_amounts(
                    abs(invoice_line.price_total), abs(self.amount_total)
                )
            ):
                raise UserError(_("The credit note does not match this folio reversal."))
            values = {"invoice_line_id": invoice_line.id}
        else:
            accounting_move.ensure_one()
            if (
                accounting_move.state != "posted"
                or accounting_move.move_type != "entry"
                or accounting_move.hotel_property_id != self.folio_id.property_id
                or accounting_move.hotel_folio_id != self.folio_id
            ):
                raise UserError(_("The journal reversal does not match this folio reversal."))
            values = {"accounting_move_id": accounting_move.id}
        return super(HotelFolioLine, self).write(values)

    def _create_accounting_reversal(self, reversal, reason):
        self.ensure_one()
        folio = self.folio_id
        original_invoice = self.invoice_line_id.move_id
        if original_invoice:
            reversal_date = reversal.service_date
            credit = self.env["account.move"].create(
                {
                    "move_type": "out_refund",
                    "partner_id": self.payee_partner_id.id,
                    "currency_id": self.currency_id.id,
                    "company_id": folio.property_id.company_id.id,
                    "hotel_property_id": folio.property_id.id,
                    "hotel_folio_id": folio.id,
                    "invoice_date": reversal_date,
                    "date": reversal_date,
                    "ref": _("Reversal of %(invoice)s: %(reason)s", invoice=original_invoice.display_name, reason=reason),
                    "invoice_line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": self.product_id.id,
                                "name": reversal.name,
                                "quantity": abs(self.qty),
                                "price_unit": self.price_unit,
                                "discount": self.discount,
                                "tax_ids": [(6, 0, self.tax_ids.ids)],
                            },
                        )
                    ],
                }
            )
            folio._link_account_move(credit)
            reversal._set_reversal_accounting_link(
                invoice_line=credit.invoice_line_ids[:1]
            )
            if original_invoice.state == "posted":
                credit.action_post()
                original_receivable = original_invoice.line_ids.filtered(
                    lambda item: item.account_id.account_type == "asset_receivable"
                    and not item.reconciled
                )
                credit_receivable = credit.line_ids.filtered(
                    lambda item: item.account_id.account_type == "asset_receivable"
                    and not item.reconciled
                )
                if original_receivable and credit_receivable:
                    (original_receivable | credit_receivable).reconcile()
            return credit

        original_transfer = self.accounting_move_id
        if original_transfer and original_transfer.state == "posted":
            company = folio.property_id.company_id
            amount_currency = abs(self.amount_total)
            reversal_date = reversal.service_date
            company_amount = self.currency_id._convert(
                amount_currency, company.currency_id, company, reversal_date
            )
            receivable = self.payee_partner_id.with_company(
                company
            ).property_account_receivable_id
            clearing_lines = original_transfer.line_ids.filtered(
                lambda item: item.partner_id != self.payee_partner_id
                and item.account_id != receivable
            )
            clearing = clearing_lines[:1].account_id
            if not clearing:
                raise UserError(_("The original transfer has no clearing account to reverse."))
            move_lines = [
                (
                    0,
                    0,
                    {
                        "name": reversal.name,
                        "account_id": clearing.id,
                        "debit": company_amount,
                        "credit": 0.0,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "name": reversal.name,
                        "account_id": receivable.id,
                        "partner_id": self.payee_partner_id.id,
                        "debit": 0.0,
                        "credit": company_amount,
                    },
                ),
            ]
            if self.currency_id != company.currency_id:
                move_lines[0][2].update(
                    {"currency_id": self.currency_id.id, "amount_currency": amount_currency}
                )
                move_lines[1][2].update(
                    {"currency_id": self.currency_id.id, "amount_currency": -amount_currency}
                )
            reverse_move = self.env["account.move"].create(
                {
                    "move_type": "entry",
                    "journal_id": original_transfer.journal_id.id,
                    "date": reversal_date,
                    "ref": _("Reversal of %(move)s: %(reason)s", move=original_transfer.display_name, reason=reason),
                    "hotel_property_id": folio.property_id.id,
                    "hotel_folio_id": folio.id,
                    "line_ids": move_lines,
                }
            )
            reverse_move.action_post()
            reversal._set_reversal_accounting_link(accounting_move=reverse_move)
            return reverse_move
        return self.env["account.move"]

    def unlink(self):
        for line in self:
            if line.is_posted or line.source_type != "manual":
                raise UserError(
                    _(
                        "You cannot delete a workflow-generated, posted, "
                        "or invoiced folio line."
                    )
                )
        return super().unlink()


class HotelFolioRoutingRule(models.Model):
    _name = "hotel.folio.routing.rule"
    _description = "Hotel Folio Routing Rule"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    category_id = fields.Many2one(
        "product.category",
        string="Product Category",
        required=True,
        help="Product category that triggers this routing rule.",
    )
    routing_type = fields.Selection(
        [("guest", "Route to Guest"), ("agency", "Route to Agency")],
        string="Route To",
        required=True,
        default="guest",
    )
    agency_id = fields.Many2one(
        "res.partner",
        string="Specific Agency / Entity",
        domain=[("is_hotel_agency", "=", True)],
        help="Specific agency to route to. If left empty, routes to the reservation's agency.",
    )
    active = fields.Boolean(default=True)
