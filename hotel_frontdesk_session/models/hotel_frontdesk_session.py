from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelFrontdeskSession(models.Model):
    _name = "hotel.frontdesk.session"
    _description = "Front Desk Cashier Session"
    _inherit = ["mail.thread"]
    _order = "date_opened desc, id desc"

    name = fields.Char(
        string="Session Reference",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
    )
    user_id = fields.Many2one(
        "res.users",
        string="Cashier",
        required=True,
        default=lambda self: self.env.user,
    )
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )
    state = fields.Selection(
        [("opened", "Open"), ("closed", "Closed")],
        default="opened",
        readonly=True,
        tracking=True,
    )
    date_opened = fields.Datetime(
        string="Opened Time", required=True, readonly=True, default=fields.Datetime.now
    )
    date_closed = fields.Datetime(string="Closed Time", readonly=True)
    
    opening_balance_ids = fields.One2many(
        "hotel.frontdesk.session.cash",
        "session_id",
        string="Opening Cash Control",
        domain=[("type", "=", "opening")],
    )
    closing_balance_ids = fields.One2many(
        "hotel.frontdesk.session.cash",
        "session_id",
        string="Closing Cash Control",
        domain=[("type", "=", "closing")],
    )

    total_opening_balance = fields.Monetary(
        string="Total Opening Balance", compute="_compute_balances", store=True
    )
    total_closing_balance = fields.Monetary(
        string="Total Closing Balance", compute="_compute_balances", store=True
    )
    total_transactions = fields.Monetary(
        string="Total Transactions", compute="_compute_balances", store=True
    )
    difference = fields.Monetary(
        string="Difference", compute="_compute_balances", store=True
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="property_id.company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )

    @api.depends(
        "opening_balance_ids.amount",
        "opening_balance_ids.currency_id",
        "closing_balance_ids.amount",
        "closing_balance_ids.currency_id",
        "state",
        "date_closed",
    )
    def _compute_balances(self):
        for session in self:
            company_currency = session.currency_id or self.env.company.currency_id
            
            # Compute opening balance
            opening = 0.0
            for line in session.opening_balance_ids:
                if line.currency_id and line.currency_id != company_currency:
                    opening += line.currency_id._convert(
                        line.amount,
                        company_currency,
                        self.env.company,
                        session.date_opened.date(),
                    )
                else:
                    opening += line.amount
            session.total_opening_balance = opening

            # Compute closing balance
            closing = 0.0
            for line in session.closing_balance_ids:
                if line.currency_id and line.currency_id != company_currency:
                    closing_date = (session.date_closed or fields.Datetime.now()).date()
                    closing += line.currency_id._convert(
                        line.amount, company_currency, self.env.company, closing_date
                    )
                else:
                    closing += line.amount
            session.total_closing_balance = closing

            # Calculate total transactions (payments created by this cashier during this session)
            payments_domain = [
                ("create_uid", "=", session.user_id.id),
                ("create_date", ">=", session.date_opened),
            ]
            if session.date_closed:
                payments_domain.append(("create_date", "<=", session.date_closed))
            else:
                payments_domain.append(("create_date", "<=", fields.Datetime.now()))

            payments = self.env["account.payment"].sudo().search(payments_domain)
            tx_total = 0.0
            for pay in payments:
                if pay.currency_id != company_currency:
                    tx_total += pay.currency_id._convert(
                        pay.amount,
                        company_currency,
                        self.env.company,
                        pay.date or fields.Date.today(),
                    )
                else:
                    tx_total += pay.amount
            session.total_transactions = tx_total

            # Difference: closing - (opening + transactions)
            session.difference = session.total_closing_balance - (
                session.total_opening_balance + session.total_transactions
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.frontdesk.session")
                    or _("New")
                )
        return super().create(vals_list)

    def action_close_session(self):
        self.ensure_one()
        if self.state != "opened":
            raise UserError(_("This session is already closed."))
        
        # Verify that closing cash control has lines defined
        if not self.closing_balance_ids:
            raise UserError(_("Please define the closing cash count before closing the session."))

        self.write(
            {
                "state": "closed",
                "date_closed": fields.Datetime.now(),
            }
        )
        return True


class HotelFrontdeskSessionCash(models.Model):
    _name = "hotel.frontdesk.session.cash"
    _description = "Session Cash Entry"

    session_id = fields.Many2one(
        "hotel.frontdesk.session", string="Session", required=True, ondelete="cascade"
    )
    currency_id = fields.Many2one("res.currency", string="Currency", required=True)
    amount = fields.Monetary(
        string="Amount", required=True, currency_field="currency_id"
    )
    type = fields.Selection(
        [("opening", "Opening Count"), ("closing", "Closing Count")],
        string="Type",
        required=True,
    )
