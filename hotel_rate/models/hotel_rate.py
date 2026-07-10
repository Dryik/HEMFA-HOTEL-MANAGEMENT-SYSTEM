from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )
    room_type_id = fields.Many2one(
        "hotel.room.type",
        string="Room Type",
        required=True,
    )
    date_start = fields.Date(string="Start Date", required=True)
    date_end = fields.Date(string="End Date", required=True)
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

    _sql_constraints = [
        (
            "date_range_check",
            "CHECK (date_end >= date_start)",
            "End date must be greater than or equal to start date.",
        ),
        (
            "positive_rate_check",
            "CHECK (rate_price >= 0)",
            "Rate price must be positive.",
        ),
    ]

    @api.constrains("date_start", "date_end", "property_id", "room_type_id", "guest_type")
    def _check_overlapping_rules(self):
        for rule in self:
            overlapping = self.search(
                [
                    ("id", "!=", rule.id),
                    ("property_id", "=", rule.property_id.id),
                    ("room_type_id", "=", rule.room_type_id.id),
                    ("guest_type", "=", rule.guest_type),
                    ("date_start", "<=", rule.date_end),
                    ("date_end", ">=", rule.date_start),
                ]
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
        default=lambda self: self.env["hotel.property"].search([], limit=1),
    )
    min_occupancy = fields.Integer(string="Min Occupancy (%)", required=True)
    max_occupancy = fields.Integer(string="Max Occupancy (%)", required=True)
    multiplier = fields.Float(
        string="Rate Multiplier",
        required=True,
        default=1.0,
        help="Multiplication factor to apply to the nightly rate (e.g. 1.20 for +20% price).",
    )

    _sql_constraints = [
        (
            "occupancy_range_check",
            "CHECK (max_occupancy >= min_occupancy AND min_occupancy >= 0 AND max_occupancy <= 100)",
            "Occupancy percentages must be between 0 and 100, and max occupancy must be greater than or equal to min occupancy.",
        ),
        (
            "positive_multiplier_check",
            "CHECK (multiplier > 0)",
            "Multiplier must be positive.",
        ),
    ]

    @api.constrains("min_occupancy", "max_occupancy", "property_id")
    def _check_overlapping_bands(self):
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
