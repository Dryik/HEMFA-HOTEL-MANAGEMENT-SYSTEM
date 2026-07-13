from datetime import date, datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelProperty(models.Model):
    _name = "hotel.property"
    _description = "Hotel Property"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(help="Short code used in references and reports.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    address_id = fields.Many2one(
        "res.partner",
        string="Address",
        domain=[("is_company", "=", True)],
    )
    # Hotel business day: charges run noon to noon (client requirement).
    day_start_hour = fields.Float(
        string="Business Day Start",
        default=12.0,
        tracking=True,
        help="Hour at which the hotel business day rolls over. "
        "A stay is charged per business day from this hour to the same "
        "hour the next calendar day.",
    )
    timezone = fields.Selection(
        selection=lambda self: [(tz, tz) for tz in pytz.all_timezones],
        required=True,
        default=lambda self: self.env.user.tz or "Africa/Tripoli",
        help="Timezone used to convert the property's business day to UTC.",
    )
    current_business_date = fields.Date(
        string="Current Business Date",
        default=fields.Date.today,
        tracking=True,
        help="Operational date rolled forward by the night audit.",
    )
    late_checkout_grace_hours = fields.Float(
        string="Late Checkout Grace (hours)",
        default=0.0,
        help="Hours after the business day start during which checkout "
        "incurs no late charge.",
    )
    cancellation_policy = fields.Selection(
        [
            ("none", "No Automatic Charge"),
            ("fixed", "Fixed Fee"),
            ("first_night", "First Night"),
            ("percent", "Percentage of Stay"),
        ],
        default="none",
        required=True,
    )
    cancellation_grace_hours = fields.Float(
        string="Cancellation Grace (hours)", default=0.0
    )
    cancellation_fee_value = fields.Float(
        string="Cancellation Fee / Percentage", default=0.0
    )
    no_show_policy = fields.Selection(
        [
            ("none", "No Automatic Charge"),
            ("fixed", "Fixed Fee"),
            ("first_night", "First Night"),
            ("percent", "Percentage of Stay"),
        ],
        default="none",
        required=True,
    )
    no_show_grace_hours = fields.Float(string="No-show Grace (hours)", default=0.0)
    no_show_fee_value = fields.Float(string="No-show Fee / Percentage", default=0.0)
    floor_ids = fields.One2many("hotel.floor", "property_id", string="Floors")
    room_ids = fields.One2many("hotel.room", "property_id", string="Rooms")
    room_count = fields.Integer(compute="_compute_room_count")
    sellable_room_count = fields.Integer(
        compute="_compute_room_count",
        help="Rooms available for sale: excludes out-of-order and "
        "admin-use rooms. Denominator for occupancy-based pricing.",
    )

    _code_company_uniq = models.Constraint(
        "unique (code, company_id)",
        "Property code must be unique per company.",
    )

    @api.depends("room_ids.active", "room_ids.is_sellable")
    def _compute_room_count(self):
        for prop in self:
            rooms = prop.room_ids.filtered("active")
            prop.room_count = len(rooms)
            prop.sellable_room_count = len(rooms.filtered("is_sellable"))

    @api.model
    def _get_default_property(self):
        """Return the current user's explicit default/first assigned property."""
        user = self.env.user
        assigned = user.hotel_property_ids.filtered(
            lambda prop: prop.active and prop.company_id in self.env.companies
        )
        if user.default_hotel_property_id in assigned:
            return user.default_hotel_property_id
        if assigned:
            return assigned.sorted("name")[:1]
        # Superuser-mode jobs and technical administrators have unrestricted
        # property access, so keep the clean-database dashboard usable before an
        # explicit default is configured. Normal hotel users still require an
        # assigned property.
        if self.env.su or user.has_group("base.group_system"):
            return self.search(
                [("company_id", "in", self.env.companies.ids)],
                order="name, id",
                limit=1,
            )
        return self.browse()

    def _day_start_parts(self):
        self.ensure_one()
        hours = int(self.day_start_hour)
        minutes = int(round((self.day_start_hour - hours) * 60))
        if minutes == 60:
            hours += 1
            minutes = 0
        return hours, minutes

    def get_business_date(self, moment=None):
        """Return the property-local business date containing a UTC moment."""
        self.ensure_one()
        moment = fields.Datetime.to_datetime(moment or fields.Datetime.now())
        if moment.tzinfo is None:
            moment = pytz.UTC.localize(moment)
        local_moment = moment.astimezone(pytz.timezone(self.timezone))
        hours, minutes = self._day_start_parts()
        result = local_moment.date()
        if local_moment.time().replace(tzinfo=None) < time(hours, minutes):
            result -= timedelta(days=1)
        return result

    def get_business_day_bounds(self, business_date):
        """Return naive UTC datetimes for a property-local business day."""
        self.ensure_one()
        business_date = fields.Date.to_date(business_date)
        if not isinstance(business_date, date):
            raise ValidationError(_("A valid business date is required."))
        hours, minutes = self._day_start_parts()
        timezone = pytz.timezone(self.timezone)
        start_local = timezone.localize(
            datetime.combine(business_date, time(hours, minutes)), is_dst=None
        )
        end_local = timezone.localize(
            datetime.combine(business_date + timedelta(days=1), time(hours, minutes)),
            is_dst=None,
        )
        return (
            start_local.astimezone(pytz.UTC).replace(tzinfo=None),
            end_local.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    def _set_business_date(self, business_date):
        business_date = fields.Date.to_date(business_date)
        if not business_date:
            raise ValidationError(_("A valid business date is required."))
        # This private helper is reached only after the night-audit workflow
        # has enforced its supervisor/manager role and locked the property.
        # The rollover itself must bypass the manager-only configuration ACL.
        return super(HotelProperty, self.sudo()).write(
            {"current_business_date": business_date}
        )

    def write(self, vals):
        if (
            "current_business_date" in vals
            and not (self.env.su and self.env.context.get("hotel_migration"))
        ):
            raise UserError(
                _("The active business date can only be changed by night audit or migration.")
            )
        return super().write(vals)

    @api.constrains(
        "day_start_hour",
        "cancellation_grace_hours",
        "cancellation_fee_value",
        "no_show_grace_hours",
        "no_show_fee_value",
    )
    def _check_operational_policy_values(self):
        for prop in self:
            if not 0 <= prop.day_start_hour < 24:
                raise ValidationError(
                    _("Business Day Start must be between 00:00 and 23:59.")
                )
            if min(
                prop.cancellation_grace_hours,
                prop.cancellation_fee_value,
                prop.no_show_grace_hours,
                prop.no_show_fee_value,
            ) < 0:
                raise ValidationError(_("Policy grace periods and fees cannot be negative."))
            if prop.cancellation_policy == "percent" and prop.cancellation_fee_value > 100:
                raise ValidationError(_("Cancellation percentage cannot exceed 100."))
            if prop.no_show_policy == "percent" and prop.no_show_fee_value > 100:
                raise ValidationError(_("No-show percentage cannot exceed 100."))

    def unlink(self):
        for prop in self:
            active_res = self.env["hotel.reservation"].search_count(
                [
                    ("property_id", "=", prop.id),
                    ("state", "not in", ("cancelled", "no_show")),
                ]
            )
            if active_res:
                raise UserError(_("You cannot delete property %s because it has active or completed reservations.") % prop.name)
        return super().unlink()
