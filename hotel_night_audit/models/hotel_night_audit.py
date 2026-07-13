from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelNightAudit(models.Model):
    _name = "hotel.night.audit"
    _description = "Hotel Night Audit"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Audit Reference",
        required=True,
        readonly=True,
        default=lambda self: _("New"),
    )
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        tracking=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    date = fields.Date(
        string="Audit Date",
        required=True,
        readonly=True,
        tracking=True,
        help="Operational business date being closed.",
    )
    active_run_key = fields.Char(readonly=True, copy=False, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Completed"), ("reversed", "Reversed")],
        default="draft",
        readonly=True,
        tracking=True,
    )
    run_user_id = fields.Many2one("res.users", string="Run By", readonly=True)
    run_at = fields.Datetime(readonly=True)
    reversed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    reversed_at = fields.Datetime(readonly=True, copy=False)
    reversal_reason = fields.Text(readonly=True, copy=False)
    occupancy_pct = fields.Float(string="Occupancy Rate (%)", readonly=True)
    adr = fields.Monetary(readonly=True, currency_field="currency_id")
    revpar = fields.Monetary(readonly=True, currency_field="currency_id")
    revenue_posted = fields.Monetary(
        string="Revenue Posted", readonly=True, currency_field="currency_id"
    )
    tax_posted = fields.Monetary(readonly=True, currency_field="currency_id")
    room_count = fields.Integer(readonly=True)
    sellable_room_count = fields.Integer(readonly=True)
    occupied_room_count = fields.Integer(readonly=True)
    arrivals_count = fields.Integer(readonly=True)
    departures_count = fields.Integer(readonly=True)
    no_show_count = fields.Integer(readonly=True)
    closed_session_count = fields.Integer(readonly=True)
    session_transaction_total = fields.Monetary(
        readonly=True, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="property_id.company_id.currency_id",
        string="Currency",
        readonly=True,
    )
    line_ids = fields.One2many(
        "hotel.night.audit.line", "audit_id", string="Audit Details", readonly=True
    )

    _active_run_key_uniq = models.Constraint(
        "unique (active_run_key)",
        "Only one active night audit is allowed per property and business date.",
    )

    @api.onchange("property_id")
    def _onchange_property_id(self):
        if self.property_id:
            self.date = self.property_id.current_business_date

    @api.model_create_multi
    def create(self, vals_list):
        keys = set()
        protected = {
            "active_run_key",
            "run_user_id",
            "run_at",
            "reversed_by_id",
            "reversed_at",
            "reversal_reason",
            "occupancy_pct",
            "adr",
            "revpar",
            "revenue_posted",
            "tax_posted",
            "room_count",
            "sellable_room_count",
            "occupied_room_count",
            "arrivals_count",
            "departures_count",
            "no_show_count",
            "closed_session_count",
            "session_transaction_total",
            "line_ids",
        }
        for vals in vals_list:
            if not self.env.su and (
                vals.get("state", "draft") != "draft"
                or vals.get("name") not in (None, False, _("New"))
                or protected.intersection(vals)
            ):
                raise UserError(_("Night-audit results can only be created by the run action."))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.night.audit")
                    or _("New")
                )
            property_id = vals.get("property_id")
            if not property_id:
                property_id = self.env["hotel.property"]._get_default_property().id
                vals["property_id"] = property_id
            prop = self.env["hotel.property"].browse(property_id)
            if prop:
                requested_date = fields.Date.to_date(
                    vals.get("date") or prop.current_business_date
                )
                if not self.env.su and requested_date != prop.current_business_date:
                    raise UserError(_("A night audit must use the active property business date."))
                vals["date"] = requested_date
            if prop and vals.get("date"):
                key = f"{prop.id}:{vals['date']}"
                if key in keys:
                    raise UserError(_("Only one active audit is allowed per property and date."))
                keys.add(key)
                self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (9917, prop.id))
                if self.search_count([("active_run_key", "=", key)]):
                    raise UserError(_("Only one active audit is allowed per property and date."))
                vals["active_run_key"] = key
        return super().create(vals_list)

    def action_run_audit(self):
        self.ensure_one()
        if not self.env.user.has_group("hotel_base.group_hotel_fo_supervisor"):
            raise UserError(
                _("Only a Front Office Supervisor or Hotel Manager can run the night audit.")
            )
        if self.state != "draft":
            raise UserError(_("This night audit is not in draft."))

        prop = self.property_id
        self.env.cr.execute(
            "SELECT id FROM hotel_property WHERE id = %s FOR UPDATE", [prop.id]
        )
        prop.invalidate_recordset(["current_business_date"])
        if prop.current_business_date != self.date:
            raise UserError(
                _(
                    "Audit date %(audit_date)s does not match the property's current "
                    "business date %(property_date)s.",
                    audit_date=self.date,
                    property_date=prop.current_business_date,
                )
            )
        duplicate = self.search_count(
            [
                ("id", "!=", self.id),
                ("property_id", "=", prop.id),
                ("date", "=", self.date),
                ("state", "=", "done"),
            ]
        )
        if duplicate:
            raise UserError(_("This property and business date are already audited."))

        business_start, business_end = prop.get_business_day_bounds(self.date)
        active_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "checked_in"),
                ("checkin_date", "<", business_end),
                ("checkout_date", ">", business_start),
            ]
        )
        total_company_revenue = 0.0
        total_company_tax = 0.0
        details = []
        for reservation in active_reservations:
            folio = reservation.folio_ids[:1]
            if not folio:
                folio = self.env["hotel.folio"].create(
                    {"reservation_id": reservation.id}
                )
            source_key = (
                f"night_audit:{prop.id}:{self.date}:{reservation.id}:{self.id}"
            )
            existing = self.env["hotel.folio.line"].search(
                [("source_key", "=", source_key)], limit=1
            )
            if existing:
                details.append(self._detail_values(reservation, folio, existing, "skipped"))
                continue
            line = folio._add_workflow_charge(
                product=reservation.room_type_id.product_id,
                qty=1.0,
                price_unit=reservation.rate_night,
                date=business_start,
                source_type="room_night",
                source_reference=self.name,
                source_key=source_key,
            )
            line.write({"name": _("Room Charge - %s") % self.date})
            line._set_operational_lock("night_audit")
            company_amount = line.currency_id._convert(
                line.amount_untaxed,
                prop.company_id.currency_id,
                prop.company_id,
                self.date,
            )
            total_company_revenue += company_amount
            total_company_tax += line.currency_id._convert(
                line.amount_tax,
                prop.company_id.currency_id,
                prop.company_id,
                self.date,
            )
            details.append(self._detail_values(reservation, folio, line, "posted"))

        no_show_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "confirmed"),
                ("checkin_date", "<", business_end),
            ]
        )
        for reservation in no_show_reservations:
            reservation.action_no_show()
            details.append(
                {
                    "reservation_id": reservation.id,
                    "folio_id": reservation.folio_ids[:1].id,
                    "status": "no_show",
                    "occupancy_status": "no_show",
                    "charge_currency_id": reservation.currency_id.id,
                    "confirmed_rate": reservation.rate_night,
                }
            )

        all_rooms = self.env["hotel.room"].search(
            [("property_id", "=", prop.id), ("active", "=", True)]
        )
        sellable_count = len(all_rooms.filtered("is_sellable"))
        occupied_count = len(active_reservations)
        occupancy = 100.0 * occupied_count / sellable_count if sellable_count else 0.0
        arrivals = self.env["hotel.reservation"].search_count(
            [
                ("property_id", "=", prop.id),
                ("checkin_date", ">=", business_start),
                ("checkin_date", "<", business_end),
                ("state", "not in", ("cancelled",)),
            ]
        )
        departures = self.env["hotel.reservation"].search_count(
            [
                ("property_id", "=", prop.id),
                ("checkout_date", ">=", business_start),
                ("checkout_date", "<", business_end),
                ("state", "not in", ("cancelled", "no_show")),
            ]
        )
        sessions = self.env["hotel.frontdesk.session"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "closed"),
                ("date_closed", ">=", business_start),
                ("date_closed", "<", business_end),
            ]
        )
        session_total = sum(sessions.mapped("total_transactions"))
        session_count = len(sessions)
        self.env["hotel.night.audit.line"]._create_for_audit(self, details)
        prop._set_business_date(self.date + timedelta(days=1))
        self._write_audit_values(
            {
                "state": "done",
                "run_user_id": self.env.user.id,
                "run_at": fields.Datetime.now(),
                "occupancy_pct": occupancy,
                "revenue_posted": total_company_revenue,
                "tax_posted": total_company_tax,
                "room_count": len(all_rooms),
                "sellable_room_count": sellable_count,
                "occupied_room_count": occupied_count,
                "arrivals_count": arrivals,
                "departures_count": departures,
                "no_show_count": len(no_show_reservations),
                "closed_session_count": session_count,
                "session_transaction_total": session_total,
                "adr": total_company_revenue / occupied_count if occupied_count else 0.0,
                "revpar": total_company_revenue / sellable_count if sellable_count else 0.0,
            }
        )
        return True

    def _detail_values(self, reservation, folio, folio_line, status):
        self.ensure_one()
        company_currency = self.property_id.company_id.currency_id
        company_amount = folio_line.currency_id._convert(
            folio_line.amount_total,
            company_currency,
            self.property_id.company_id,
            self.date,
        )
        fx_rate = self.env["res.currency"]._get_conversion_rate(
            folio_line.currency_id,
            company_currency,
            self.property_id.company_id,
            self.date,
        )
        return {
            "reservation_id": reservation.id,
            "folio_id": folio.id,
            "folio_line_id": folio_line.id,
            "amount_posted": company_amount if status == "posted" else 0.0,
            "charge_amount_currency": folio_line.amount_total,
            "charge_currency_id": folio_line.currency_id.id,
            "confirmed_rate": reservation.rate_night,
            "tax_basis": folio_line.amount_untaxed,
            "tax_amount": folio_line.amount_tax,
            "effective_fx_rate": fx_rate,
            "occupancy_status": "occupied",
            "status": status,
        }

    def action_reverse(self, reason=None):
        self.ensure_one()
        reason = reason or self.env.context.get("night_audit_reversal_reason")
        if not self.env.user.has_group("hotel_base.group_hotel_manager"):
            raise UserError(_("Only a Hotel Manager can reverse a night audit."))
        if self.state != "done" or not reason or not reason.strip():
            raise UserError(_("A completed audit and a reversal reason are required."))
        later = self.search_count(
            [
                ("property_id", "=", self.property_id.id),
                ("date", ">", self.date),
                ("state", "=", "done"),
            ]
        )
        if later:
            raise UserError(_("Reverse later completed audits first."))
        self.env.cr.execute(
            "SELECT id FROM hotel_property WHERE id = %s FOR UPDATE",
            [self.property_id.id],
        )
        posted_lines = self.line_ids.filtered(
            lambda line: line.status == "posted" and line.folio_line_id
        )
        for detail in posted_lines:
            detail.folio_line_id.action_reverse(reason.strip())
        for detail in self.line_ids.filtered(lambda line: line.status == "no_show"):
            if detail.reservation_id.state == "no_show":
                detail.reservation_id._write_workflow_values({"state": "confirmed"})
        if self.property_id.current_business_date == self.date + timedelta(days=1):
            self.property_id._set_business_date(self.date)
        self._write_audit_values(
            {
                "state": "reversed",
                "active_run_key": False,
                "reversed_by_id": self.env.user.id,
                "reversed_at": fields.Datetime.now(),
                "reversal_reason": reason.strip(),
            }
        )
        return True

    def _write_audit_values(self, values):
        return super(HotelNightAudit, self).write(values)

    def action_open_reversal_wizard(self):
        self.ensure_one()
        if self.state != "done":
            raise UserError(_("Only a completed audit can be reversed."))
        return {
            "name": _("Reverse Night Audit"),
            "type": "ir.actions.act_window",
            "res_model": "hotel.night.audit.reversal.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_audit_id": self.id},
        }

    def write(self, vals):
        action_controlled = {
                "name",
                "property_id",
                "date",
                "active_run_key",
                "state",
                "run_user_id",
                "run_at",
                "reversed_by_id",
                "reversed_at",
                "reversal_reason",
                "occupancy_pct",
                "adr",
                "revpar",
                "revenue_posted",
                "tax_posted",
                "room_count",
                "sellable_room_count",
                "occupied_room_count",
                "arrivals_count",
                "departures_count",
                "no_show_count",
                "closed_session_count",
                "session_transaction_total",
                "line_ids",
        }
        if action_controlled.intersection(vals):
            raise UserError(
                _(
                    "Night-audit state and snapshots can only be changed "
                    "through the run or manager reversal actions."
                )
            )
        if self.filtered(lambda audit: audit.state in ("done", "reversed")):
            raise UserError(_("Completed night audits are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda audit: audit.state != "draft"):
            raise UserError(_("Completed or reversed night audits cannot be deleted."))
        return super().unlink()


class HotelNightAuditLine(models.Model):
    _name = "hotel.night.audit.line"
    _description = "Hotel Night Audit Detail Line"

    audit_id = fields.Many2one(
        "hotel.night.audit", string="Audit", required=True, ondelete="cascade"
    )
    reservation_id = fields.Many2one("hotel.reservation", string="Reservation")
    room_id = fields.Many2one(
        related="reservation_id.room_id", string="Room", store=True, readonly=True
    )
    partner_id = fields.Many2one(
        related="reservation_id.partner_id", string="Guest", store=True, readonly=True
    )
    folio_id = fields.Many2one("hotel.folio", string="Folio")
    folio_line_id = fields.Many2one("hotel.folio.line", readonly=True, copy=False)
    amount_posted = fields.Monetary(currency_field="currency_id", readonly=True)
    charge_amount_currency = fields.Monetary(
        currency_field="charge_currency_id", readonly=True
    )
    charge_currency_id = fields.Many2one("res.currency", readonly=True)
    confirmed_rate = fields.Monetary(
        currency_field="charge_currency_id", readonly=True
    )
    tax_basis = fields.Monetary(currency_field="charge_currency_id", readonly=True)
    tax_amount = fields.Monetary(currency_field="charge_currency_id", readonly=True)
    effective_fx_rate = fields.Float(readonly=True, digits=0)
    occupancy_status = fields.Selection(
        [("occupied", "Occupied"), ("no_show", "No Show")], readonly=True
    )
    status = fields.Selection(
        [
            ("posted", "Room Night Charged"),
            ("skipped", "Already Charged"),
            ("no_show", "No Show Rollover"),
        ],
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="audit_id.currency_id", string="Currency"
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise UserError(_("Night-audit details can only be created by the audit run."))

    @api.model
    def _create_for_audit(self, audit, values_list):
        audit.ensure_one()
        if audit.state != "draft":
            raise UserError(_("Night-audit details require a draft audit."))
        prepared = [dict(values, audit_id=audit.id) for values in values_list]
        return super(HotelNightAuditLine, self).create(prepared)

    def write(self, vals):
        if self.mapped("audit_id").filtered(
            lambda audit: audit.state in ("done", "reversed")
        ):
            raise UserError(_("Completed night-audit details are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.mapped("audit_id").filtered(
            lambda audit: audit.state in ("done", "reversed")
        ):
            raise UserError(_("Completed night-audit details cannot be deleted."))
        return super().unlink()
