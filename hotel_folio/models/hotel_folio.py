from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
    amount_total = fields.Monetary(
        string="Total Charges", compute="_compute_totals", store=True
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

    @api.depends("line_ids.amount", "invoice_ids.amount_total", "invoice_ids.payment_state")
    def _compute_totals(self):
        for folio in self:
            folio.amount_total = sum(folio.line_ids.mapped("amount"))
            # Sum up total of paid invoices (or posted payments/invoices)
            posted_invoices = folio.invoice_ids.filtered(lambda inv: inv.state == "posted")
            # For this simplified model, we can sum up payment registration or active invoice totals
            # paid_amount = sum(inv.amount_total - inv.amount_residual for inv in posted_invoices)
            # Let's count paid invoices as fully paid, or use the invoice amount paid
            folio.amount_paid = sum(
                (inv.amount_total - inv.amount_residual) for inv in posted_invoices
            )
            folio.amount_due = folio.amount_total - folio.amount_paid

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.folio")
                    or _("New")
                )
        return super().create(vals_list)

    def add_charge(self, product, qty=1.0, price_unit=None, date=None):
        self.ensure_one()
        if price_unit is None:
            price_unit = product.list_price

        # Determine payee using routing rules
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

        # Determine taxes
        taxes = product.taxes_id.filtered(lambda t: t.company_id == self.env.company)

        line = self.env["hotel.folio.line"].create(
            {
                "folio_id": self.id,
                "product_id": product.id,
                "name": product.display_name or product.name,
                "qty": qty,
                "price_unit": price_unit,
                "payee_partner_id": payee.id,
                "date": date or fields.Datetime.now(),
                "tax_ids": [(6, 0, taxes.ids)],
            }
        )
        return line

    def action_create_invoice(self, partner_id=None):
        self.ensure_one()
        if not partner_id:
            # Default to guest partner
            partner_id = self.partner_id

        # Find uninvoiced lines for this payee partner
        lines_to_invoice = self.line_ids.filtered(
            lambda l: l.payee_partner_id == partner_id and not l.invoice_line_id
        )
        if not lines_to_invoice:
            raise UserError(_("No uninvoiced lines found for this payee."))

        # Create account.move
        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": partner_id.id,
            "currency_id": self.currency_id.id,
            "company_id": self.reservation_id.property_id.company_id.id or self.env.company.id,
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "name": line.name,
                        "quantity": line.qty,
                        "price_unit": line.price_unit,
                        "tax_ids": [(6, 0, line.tax_ids.ids)],
                    },
                )
                for line in lines_to_invoice
            ],
        }
        invoice = self.env["account.move"].create(invoice_vals)
        self.write({"invoice_ids": [(4, invoice.id)]})

        # Link folio lines to invoice lines
        for line, inv_line in zip(lines_to_invoice, invoice.invoice_line_ids):
            line.invoice_line_id = inv_line.id
            line.is_posted = True

        return {
            "name": _("Invoice"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": invoice.id,
            "target": "current",
        }

    def unlink(self):
        for folio in self:
            if any(line.is_posted for line in folio.line_ids):
                raise UserError(_("You cannot delete a folio with posted or invoiced charges."))
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
    tax_ids = fields.Many2many("account.tax", string="Taxes")
    amount = fields.Monetary(
        string="Amount", compute="_compute_amount", store=True, currency_field="currency_id"
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
    is_posted = fields.Boolean(
        string="Posted",
        default=False,
        help="If checked, the charge is locked (e.g. invoiced or processed by night audit).",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="folio_id.currency_id",
        store=True,
        readonly=True,
    )

    @api.depends("qty", "price_unit", "tax_ids")
    def _compute_amount(self):
        for line in self:
            # Basic subtotal calculation. In standard Odoo we'd use tax computation,
            # but for folio lines let's calculate subtotal before tax to keep it simple and robust,
            # or sum up with taxes. Let's calculate standard untaxed subtotal.
            line.amount = line.price_unit * line.qty

    def unlink(self):
        for line in self:
            if line.is_posted:
                raise UserError(_("You cannot delete a posted or invoiced folio line."))
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
        default=lambda self: self.env["hotel.property"].search([], limit=1),
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
