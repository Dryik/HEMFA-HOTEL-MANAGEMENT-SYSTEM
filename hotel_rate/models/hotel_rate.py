import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


def _install_exclusion_constraint(env, table, name, expression):
    """Install a concurrency-safe overlap guard when btree_gist is available."""
    cr = env.cr
    cr.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
    if not cr.fetchone():
        _logger.info(
            "btree_gist is unavailable; %s overlap enforcement uses ORM validation.",
            table,
        )
        return
    try:
        with cr.savepoint():
            cr.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", [name])
            if not cr.fetchone():
                cr.execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT {name} {expression}"
                )
    except Exception:
        _logger.warning(
            "Could not install %s; resolve existing overlapping configuration before retrying.",
            name,
        )


class HotelRateRule(models.Model):
    _name = "hotel.rate.rule"
    _description = "Hotel Rate Rule"
    _order = "sequence, date_start, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    room_type_id = fields.Many2one(
        "hotel.room.type",
        string="Room Type",
        required=True,
    )
    date_start = fields.Date(string="Start Date", required=True)
    date_end = fields.Date(string="End Date", required=True)
    seasonal_pricing_id = fields.Many2one(
        "hotel.seasonal.pricing", string="Seasonal Plan", ondelete="set null"
    )
    weekday_ids = fields.Many2many(
        "hotel.rate.weekday", string="Weekdays"
    )
    guest_type = fields.Selection(
        [
            ("all", "All Nationalities"),
            ("local", "Libyan National"),
            ("foreign", "Foreigner"),
        ],
        string="Guest Nationality Type",
        default="all",
        required=True,
        help="Applies this rate depending on the guest's nationality.",
    )
    rate_price = fields.Monetary(
        string="Nightly Rate", required=True, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    _date_range_check = models.Constraint(
        "CHECK (date_end >= date_start)",
        "End date must be greater than or equal to start date.",
    )
    _positive_rate_check = models.Constraint(
        "CHECK (rate_price >= 0)",
        "Rate price must be positive.",
    )

    def init(self):
        super().init()
        # Weekday-specific rules may legitimately share the same calendar
        # range.  The former date-only exclusion constraint could not express
        # the M2M weekday intersection, so concurrency is serialized by the
        # advisory property lock in the ORM constraint below.
        self.env.cr.execute(
            "ALTER TABLE hotel_rate_rule "
            "DROP CONSTRAINT IF EXISTS hotel_rate_rule_no_overlap"
        )

    @api.constrains(
        "date_start",
        "date_end",
        "property_id",
        "room_type_id",
        "guest_type",
        "seasonal_pricing_id",
    )
    def _check_overlapping_rules(self):
        # Serialize rate configuration per property.  A Python-only overlap
        # search can otherwise let two concurrent transactions validate
        # against the same pre-insert snapshot.
        for property_id in sorted(self.property_id.ids):
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", (8821, property_id)
            )
            self.env.cr.execute(
                "UPDATE hotel_property SET id = id WHERE id = %s", [property_id]
            )
        for rule in self:
            if rule.room_type_id.property_id and rule.room_type_id.property_id != rule.property_id:
                raise ValidationError(
                    _("The room type must be shared or belong to the rate rule property.")
                )
            if rule.seasonal_pricing_id and (
                rule.seasonal_pricing_id.property_id != rule.property_id
                or rule.date_start < rule.seasonal_pricing_id.date_start
                or rule.date_end > rule.seasonal_pricing_id.date_end
            ):
                raise ValidationError(
                    _("A rate rule must stay within its seasonal plan and hotel.")
                )
            overlapping_candidates = self.search(
                [
                    ("id", "!=", rule.id),
                    ("property_id", "=", rule.property_id.id),
                    ("room_type_id", "=", rule.room_type_id.id),
                    ("guest_type", "=", rule.guest_type),
                    ("date_start", "<=", rule.date_end),
                    ("date_end", ">=", rule.date_start),
                ]
            )
            rule_weekdays = set(rule.weekday_ids.mapped("code"))
            overlapping = overlapping_candidates.filtered(
                lambda candidate: (
                    not rule_weekdays
                    or not candidate.weekday_ids
                    or bool(rule_weekdays.intersection(candidate.weekday_ids.mapped("code")))
                )
            )
            if overlapping:
                raise ValidationError(
                    _(
                        "This rate rule overlaps with an existing rate rule: %(overlap)s",
                        overlap=overlapping[0].name,
                    )
                )


class HotelRateOccupancyBand(models.Model):
    _name = "hotel.rate.occupancy.band"
    _description = "Hotel Rate Occupancy Band"
    _order = "min_occupancy"

    name = fields.Char(required=True, translate=True)
    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    min_occupancy = fields.Integer(string="Min Occupancy (%)", required=True)
    max_occupancy = fields.Integer(string="Max Occupancy (%)", required=True)
    multiplier = fields.Float(
        string="Rate Factor (1.0 = no change)",
        required=True,
        default=1.0,
        help="Multiplication factor applied to the nightly rate "
        "(e.g. 1.20 = +20%, 0.90 = −10%).",
    )
    adjustment_pct = fields.Float(
        string="Adjustment %",
        compute="_compute_adjustment_pct",
        help="Percentage markup or discount implied by the rate factor.",
    )

    @api.depends("multiplier")
    def _compute_adjustment_pct(self):
        for band in self:
            band.adjustment_pct = (band.multiplier - 1.0) * 100.0

    _occupancy_range_check = models.Constraint(
        "CHECK (max_occupancy >= min_occupancy AND min_occupancy >= 0 AND max_occupancy <= 100)",
        "Occupancy percentages must be between 0 and 100, and max occupancy must be greater than or equal to min occupancy.",
    )
    _positive_multiplier_check = models.Constraint(
        "CHECK (multiplier > 0)",
        "Multiplier must be positive.",
    )

    def init(self):
        super().init()
        _install_exclusion_constraint(
            self.env,
            "hotel_rate_occupancy_band",
            "hotel_rate_occupancy_band_no_overlap",
            """EXCLUDE USING gist (
                property_id WITH =,
                int4range(min_occupancy, max_occupancy, '[]') WITH &&
            )""",
        )

    @api.constrains("min_occupancy", "max_occupancy", "property_id")
    def _check_overlapping_bands(self):
        for property_id in sorted(self.property_id.ids):
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", (8821, property_id)
            )
            self.env.cr.execute(
                "UPDATE hotel_property SET id = id WHERE id = %s", [property_id]
            )
        for band in self:
            overlapping = self.search(
                [
                    ("id", "!=", band.id),
                    ("property_id", "=", band.property_id.id),
                    ("min_occupancy", "<=", band.max_occupancy),
                    ("max_occupancy", ">=", band.min_occupancy),
                ]
            )
            if overlapping:
                raise ValidationError(
                    _(
                        "This occupancy band overlaps with an existing band: %(overlap)s",
                        overlap=overlapping[0].name,
                    )
                )
