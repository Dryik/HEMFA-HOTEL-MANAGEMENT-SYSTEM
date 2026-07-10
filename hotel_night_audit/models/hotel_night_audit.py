from datetime import timedelta
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HotelNightAudit(models.Model):
    _name = "hotel.night.audit"
    _description = "Hotel Night Audit"
    _order = "date desc, id desc"

    name = fields.Char(string="Audit Reference", required=True, readonly=True, default=lambda self: _("New"))
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )
    date = fields.Date(
        string="Audit Date",
        required=True,
        readonly=True,
        help="Operational business date being closed.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Completed")],
        default="draft",
        readonly=True,
    )
    run_user_id = fields.Many2one("res.users", string="Run By", readonly=True)
    occupancy_pct = fields.Float(string="Occupancy Rate (%)", readonly=True)
    revenue_posted = fields.Monetary(
        string="Revenue Posted", readonly=True, currency_field="currency_id"
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

    @api.onchange("property_id")
    def _onchange_property_id(self):
        if self.property_id:
            self.date = self.property_id.current_business_date

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hotel.night.audit")
                    or _("New")
                )
            if "property_id" in vals and "date" not in vals:
                prop = self.env["hotel.property"].browse(vals["property_id"])
                vals["date"] = prop.current_business_date or fields.Date.today()
        return super().create(vals_list)

    def action_run_audit(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("This night audit is already completed."))

        prop = self.property_id
        audit_date = self.date

        # Double check date matches property's current business date
        if prop.current_business_date != audit_date:
            raise UserError(
                _(
                    "Audit date %(audit_date)s does not match the property's current business date %(prop_date)s.",
                    audit_date=audit_date,
                    prop_date=prop.current_business_date,
                )
            )

        # Define the audit reference datetime in the middle of the business day (18:00)
        # to ensure comparisons with Datetime fields match correctly.
        audit_datetime = fields.Datetime.to_datetime(audit_date).replace(
            hour=18, minute=0, second=0
        )

        # 1. Post Room Night Charges for all checked_in stays
        active_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "checked_in"),
                ("checkin_date", "<=", audit_datetime),
                ("checkout_date", ">", audit_datetime),
            ]
        )

        total_posted = 0.0
        details = []

        for res in active_reservations:
            # We assume each reservation should have a folio
            folio = res.folio_ids and res.folio_ids[0]
            if not folio:
                folio = self.env["hotel.folio"].create({"reservation_id": res.id})

            # Check if room night has already been charged for this audit_date
            charge_desc = _("Room Charge - %s") % audit_date
            already_charged = self.env["hotel.folio.line"].search_count(
                [
                    ("folio_id", "=", folio.id),
                    ("product_id", "=", res.room_type_id.product_id.id),
                    ("name", "=", charge_desc),
                ]
            )

            if not already_charged:
                # Add the nightly charge to the folio
                line = folio.add_charge(
                    product=res.room_type_id.product_id,
                    qty=1.0,
                    price_unit=res.rate_night,
                    date=fields.Datetime.now(),
                )
                line.write({"name": charge_desc, "is_posted": True})
                total_posted += res.rate_night

                details.append(
                    (
                        0,
                        0,
                        {
                            "reservation_id": res.id,
                            "folio_id": folio.id,
                            "amount_posted": res.rate_night,
                            "status": "posted",
                        },
                    )
                )
            else:
                details.append(
                    (
                        0,
                        0,
                        {
                            "reservation_id": res.id,
                            "folio_id": folio.id,
                            "amount_posted": 0.0,
                            "status": "skipped",
                        },
                    )
                )

        # 2. Process No-shows (reservations expected to arrive today but still confirmed)
        # We look for confirmed bookings whose arrival date is on or before the audit date
        no_show_reservations = self.env["hotel.reservation"].search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "confirmed"),
                ("checkin_date", "<=", audit_datetime),
            ]
        )

        for res in no_show_reservations:
            res.action_no_show()
            details.append(
                (
                    0,
                    0,
                    {
                        "reservation_id": res.id,
                        "folio_id": res.folio_ids and res.folio_ids[0].id or False,
                        "amount_posted": 0.0,
                        "status": "no_show",
                    },
                )
            )

        # 3. Calculate Occupancy Snapshot
        sellable_rooms = self.env["hotel.room"].search_count(
            [
                ("property_id", "=", prop.id),
                ("is_sellable", "=", True),
            ]
        )
        occupied_rooms = len(active_reservations)
        occupancy_rate = (100.0 * occupied_rooms / sellable_rooms) if sellable_rooms else 0.0

        # 4. Roll Business Date forward
        next_date = audit_date + timedelta(days=1)
        prop.write({"current_business_date": next_date})

        # Save audit values
        self.write(
            {
                "state": "done",
                "run_user_id": self.env.user.id,
                "occupancy_pct": occupancy_rate,
                "revenue_posted": total_posted,
                "line_ids": details,
            }
        )
        return True


class HotelNightAuditLine(models.Model):
    _name = "hotel.night.audit.line"
    _description = "Hotel Night Audit Detail Line"

    audit_id = fields.Many2one(
        "hotel.night.audit", string="Audit", required=True, ondelete="cascade"
    )
    reservation_id = fields.Many2one("hotel.reservation", string="Reservation")
    folio_id = fields.Many2one("hotel.folio", string="Folio")
    amount_posted = fields.Monetary(
        string="Amount Posted", currency_field="currency_id"
    )
    status = fields.Selection(
        [
            ("posted", "Room Night Charged"),
            ("skipped", "Already Charged"),
            ("no_show", "No Show Rollover"),
        ],
        string="Audit Action",
        required=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="audit_id.currency_id", string="Currency"
    )
