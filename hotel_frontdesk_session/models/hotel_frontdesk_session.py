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
        "res.users", string="Cashier", required=True, default=lambda self: self.env.user
    )
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    company_id = fields.Many2one(
        "res.company",
        related="property_id.company_id",
        string="Company",
        readonly=True,
    )
    state = fields.Selection(
        [("opened", "Open"), ("closed", "Closed")],
        default="opened",
        readonly=True,
        tracking=True,
    )
    active_open_key = fields.Char(readonly=True, copy=False, index=True)
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
    payment_ids = fields.One2many(
        "account.payment",
        "hotel_frontdesk_session_id",
        string="Posted Payments",
        readonly=True,
    )
    reconciliation_ids = fields.One2many(
        "hotel.frontdesk.session.reconciliation",
        "session_id",
        string="Journal / Currency Reconciliation",
        readonly=True,
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
    closed_transaction_total = fields.Monetary(
        readonly=True, copy=False, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="property_id.company_id.currency_id",
        string="Company Currency",
        readonly=True,
    )

    _active_open_key_uniq = models.Constraint(
        "unique (active_open_key)",
        "A cashier can have only one open session per property.",
    )

    @api.depends(
        "opening_balance_ids.amount",
        "opening_balance_ids.currency_id",
        "opening_balance_ids.journal_id",
        "closing_balance_ids.amount",
        "closing_balance_ids.currency_id",
        "closing_balance_ids.journal_id",
        "payment_ids.state",
        "payment_ids.amount",
        "payment_ids.payment_type",
        "payment_ids.currency_id",
        "payment_ids.journal_id",
        "state",
        "date_closed",
        "closed_transaction_total",
    )
    def _compute_balances(self):
        for session in self:
            company = session.property_id.company_id or self.env.company
            company_currency = session.currency_id or company.currency_id
            opening = 0.0
            for line in session.opening_balance_ids:
                opening += session._convert_amount(
                    line.amount, line.currency_id, line.session_id.date_opened.date()
                )
            session.total_opening_balance = opening

            closing = 0.0
            for line in session.closing_balance_ids:
                close_date = (session.date_closed or fields.Datetime.now()).date()
                closing += session._convert_amount(line.amount, line.currency_id, close_date)
            session.total_closing_balance = closing

            session.total_transactions = (
                session.closed_transaction_total
                if session.state == "closed"
                else session._get_transaction_total()
            )
            session.difference = closing - opening - session.total_transactions

    def _convert_amount(self, amount, currency, conversion_date):
        self.ensure_one()
        company = self.property_id.company_id
        if currency and currency != company.currency_id:
            return currency._convert(
                amount, company.currency_id, company, conversion_date
            )
        return amount

    def _get_transaction_total(self):
        self.ensure_one()
        total = 0.0
        for payment in self.payment_ids.filtered(
            lambda record: record.state in ("in_process", "paid")
        ):
            sign = 1.0 if payment.payment_type == "inbound" else -1.0
            total += self._convert_amount(
                sign * payment.amount,
                payment.currency_id,
                payment.date or fields.Date.today(),
            )
        return total

    @api.model_create_multi
    def create(self, vals_list):
        pairs = set()
        elevated = self.env.su or self.env.user.has_group(
            "hotel_base.group_hotel_fo_supervisor"
        )
        for vals in vals_list:
            if not self.env.su and (
                vals.get("state", "opened") != "opened"
                or vals.get("name") not in (None, False, _("New"))
                or vals.get("date_opened")
                or vals.get("date_closed")
                or vals.get("closed_transaction_total")
                or vals.get("active_open_key")
                or vals.get("reconciliation_ids")
            ):
                raise UserError(
                    _(
                        "Cashier identity, opening timestamp, and closure values "
                        "are assigned by the session workflow."
                    )
                )
            user_id = vals.get("user_id", self.env.user.id)
            if user_id != self.env.user.id and not elevated:
                raise UserError(_("A cashier can open only their own session."))
            property_id = vals.get("property_id")
            if not property_id:
                property_id = self.env["hotel.property"]._get_default_property().id
                vals["property_id"] = property_id
            pair = (user_id, property_id)
            if pair in pairs:
                raise UserError(_("A cashier can have only one open session per property."))
            pairs.add(pair)
            self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", pair)
            if self.search_count(
                [
                    ("user_id", "=", user_id),
                    ("property_id", "=", property_id),
                    ("state", "=", "opened"),
                ]
            ):
                raise UserError(_("A cashier can have only one open session per property."))
            vals["active_open_key"] = f"{user_id}:{property_id}"
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.frontdesk.session")
                    or _("New")
                )
        return super().create(vals_list)

    def _assert_session_operator(self):
        if self.env.su or self.env.user.has_group(
            "hotel_base.group_hotel_fo_supervisor"
        ):
            return
        if self.filtered(lambda session: session.user_id != self.env.user):
            raise UserError(
                _("A cashier can operate only their own open session.")
            )

    @api.constrains("user_id", "property_id", "state")
    def _check_single_open_session(self):
        for session in self.filtered(lambda record: record.state == "opened"):
            if self.search_count(
                [
                    ("id", "!=", session.id),
                    ("user_id", "=", session.user_id.id),
                    ("property_id", "=", session.property_id.id),
                    ("state", "=", "opened"),
                ]
            ):
                raise UserError(_("A cashier can have only one open session per property."))

    def _prepare_reconciliation_values(self):
        self.ensure_one()
        grouped = {}
        for line in self.opening_balance_ids | self.closing_balance_ids:
            key = (line.journal_id.id, line.currency_id.id)
            amounts = grouped.setdefault(
                key, {"opening": 0.0, "counted": 0.0, "transactions": 0.0}
            )
            amounts["opening" if line.type == "opening" else "counted"] += line.amount
        for payment in self.payment_ids.filtered(
            lambda record: record.state in ("in_process", "paid")
        ):
            key = (payment.journal_id.id, payment.currency_id.id)
            amounts = grouped.setdefault(
                key, {"opening": 0.0, "counted": 0.0, "transactions": 0.0}
            )
            sign = 1.0 if payment.payment_type == "inbound" else -1.0
            amounts["transactions"] += sign * payment.amount
        return [
            {
                "session_id": self.id,
                "journal_id": journal_id,
                "currency_id": currency_id,
                "opening_amount": amounts["opening"],
                "transaction_amount": amounts["transactions"],
                "expected_amount": amounts["opening"] + amounts["transactions"],
                "counted_amount": amounts["counted"],
                "difference": amounts["counted"]
                - amounts["opening"]
                - amounts["transactions"],
            }
            for (journal_id, currency_id), amounts in grouped.items()
        ]

    def action_close_session(self):
        self.ensure_one()
        self._assert_session_operator()
        if self.state != "opened":
            raise UserError(_("This session is already closed."))
        if not self.closing_balance_ids:
            raise UserError(
                _("Please define the closing cash count before closing the session.")
            )
        unposted = self.payment_ids.filtered(
            lambda payment: payment.state
            not in ("in_process", "paid", "canceled", "rejected")
        )
        if unposted:
            raise UserError(_("Post or remove every linked draft payment before closing."))

        self.reconciliation_ids.sudo()._unlink_for_session_close(self)
        values = self._prepare_reconciliation_values()
        if values:
            self.env["hotel.frontdesk.session.reconciliation"].sudo()._create_for_session(
                self, values
            )
        self._write_closed_values(
            {
                "state": "closed",
                "active_open_key": False,
                "date_closed": fields.Datetime.now(),
                "closed_transaction_total": self._get_transaction_total(),
            }
        )
        return True

    def _write_closed_values(self, values):
        return super(HotelFrontdeskSession, self).write(values)

    def action_open_payment_wizard(self):
        self.ensure_one()
        if self.state != "opened":
            raise UserError(_("Payments can only be collected in an open session."))
        if not self.env.user.has_group("hotel_base.group_hotel_cashier"):
            raise UserError(_("Only a cashier can collect a session payment."))
        self._assert_session_operator()
        return {
            "name": _("Collect Hotel Payment"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.cashier.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_session_id": self.id,
                "default_property_id": self.property_id.id,
            },
        }

    def write(self, vals):
        action_controlled = {
            "name",
            "user_id",
            "property_id",
            "state",
            "active_open_key",
            "date_opened",
            "date_closed",
            "closed_transaction_total",
            "total_opening_balance",
            "total_closing_balance",
            "total_transactions",
            "difference",
            "payment_ids",
            "reconciliation_ids",
        }
        if action_controlled.intersection(vals):
            raise UserError(_("Cashier sessions can only be closed through the close action."))
        if {"opening_balance_ids", "closing_balance_ids"}.intersection(vals):
            self._assert_session_operator()
        if self.filtered(lambda session: session.state == "closed"):
            raise UserError(_("Closed cashier sessions are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda session: session.state == "closed"):
            raise UserError(_("You cannot delete a closed front desk session."))
        return super().unlink()


class HotelFrontdeskSessionCash(models.Model):
    _name = "hotel.frontdesk.session.cash"
    _description = "Session Cash Entry"

    session_id = fields.Many2one(
        "hotel.frontdesk.session", string="Session", required=True, ondelete="cascade"
    )
    currency_id = fields.Many2one("res.currency", string="Currency", required=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Journal / Drawer",
        required=True,
        domain="[('company_id', '=', parent.company_id), ('type', 'in', ('cash', 'bank'))]",
    )
    amount = fields.Monetary(
        string="Amount", required=True, currency_field="currency_id"
    )
    type = fields.Selection(
        [("opening", "Opening Count"), ("closing", "Closing Count")],
        string="Type",
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        sessions = self.env["hotel.frontdesk.session"].browse(
            [vals.get("session_id") for vals in vals_list if vals.get("session_id")]
        )
        if sessions.filtered(lambda session: session.state == "closed"):
            raise UserError(_("Cash counts cannot be added to a closed session."))
        sessions._assert_session_operator()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped("session_id")._assert_session_operator()
        if self.mapped("session_id").filtered(lambda session: session.state == "closed"):
            raise UserError(_("Cash counts on a closed session are immutable."))
        return super().write(vals)

    def unlink(self):
        self.mapped("session_id")._assert_session_operator()
        if self.mapped("session_id").filtered(lambda session: session.state == "closed"):
            raise UserError(_("Cash counts on a closed session are immutable."))
        return super().unlink()


class HotelFrontdeskSessionReconciliation(models.Model):
    _name = "hotel.frontdesk.session.reconciliation"
    _description = "Cashier Session Journal and Currency Reconciliation"
    _order = "journal_id, currency_id"

    session_id = fields.Many2one(
        "hotel.frontdesk.session", required=True, ondelete="cascade", index=True
    )
    journal_id = fields.Many2one("account.journal", required=True, readonly=True)
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    opening_amount = fields.Monetary(readonly=True, currency_field="currency_id")
    transaction_amount = fields.Monetary(readonly=True, currency_field="currency_id")
    expected_amount = fields.Monetary(readonly=True, currency_field="currency_id")
    counted_amount = fields.Monetary(readonly=True, currency_field="currency_id")
    difference = fields.Monetary(readonly=True, currency_field="currency_id")

    @api.model_create_multi
    def create(self, vals_list):
        raise UserError(_("Cashier reconciliation snapshots can only be created at closure."))

    @api.model
    def _create_for_session(self, session, values_list):
        session.ensure_one()
        if session.state != "opened":
            raise UserError(_("Cashier reconciliation snapshots require an open session."))
        prepared = [dict(values, session_id=session.id) for values in values_list]
        return super(HotelFrontdeskSessionReconciliation, self).create(prepared)

    def write(self, vals):
        raise UserError(_("Closed-session reconciliation snapshots are immutable."))

    def unlink(self):
        raise UserError(_("Closed-session reconciliation snapshots are immutable."))

    def _unlink_for_session_close(self, session):
        session.ensure_one()
        if self.filtered(lambda snapshot: snapshot.session_id != session):
            raise UserError(_("The reconciliation snapshot belongs to another session."))
        if session.state != "opened":
            raise UserError(_("Only an open session can rebuild reconciliation snapshots."))
        return super(HotelFrontdeskSessionReconciliation, self).unlink()
