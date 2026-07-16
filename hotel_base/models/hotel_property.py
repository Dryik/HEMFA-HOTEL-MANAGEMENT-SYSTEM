from datetime import date, datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HotelProperty(models.Model):
    _name = "hotel.property"
    _description = "Hotel Company Configuration"
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
        help="Timezone used to convert the company's hotel business day to UTC.",
    )
    hotel_type = fields.Selection(
        [
            ("hotel", "Hotel"),
            ("resort", "Resort"),
            ("aparthotel", "Aparthotel"),
            ("guest_house", "Guest House"),
        ],
        default="hotel",
        required=True,
        tracking=True,
    )
    tagline = fields.Char(translate=True, tracking=True)
    website_description = fields.Html(translate=True)
    website_policy = fields.Html(translate=True)
    website_banner = fields.Image(max_width=2400, max_height=1200)
    website_gallery_attachment_ids = fields.Many2many(
        "ir.attachment",
        "hotel_property_website_gallery_rel",
        "property_id",
        "attachment_id",
        string="Website Gallery",
        help="Private gallery images served only through the hotel website media route.",
    )
    website_published = fields.Boolean(
        string="Published on Website",
        default=False,
        help="Expose this company's hotel content on its configured Odoo website.",
    )
    website_review_limit = fields.Integer(default=6)
    stay_charge_policy = fields.Selection(
        [("entire_stay", "Entire Stay on Confirmation"), ("per_night", "Per Night")],
        default="entire_stay",
        required=True,
        tracking=True,
    )
    online_payment_policy = fields.Selection(
        [
            ("manual", "Manual Approval / No Online Payment"),
            ("fixed_deposit", "Fixed Deposit"),
            ("percent_deposit", "Percentage Deposit"),
            ("full", "Full Prepayment"),
        ],
        default="manual",
        required=True,
        tracking=True,
    )
    online_deposit_value = fields.Float(
        string="Online Deposit / Percentage", default=0.0
    )
    online_hold_minutes = fields.Integer(default=15, required=True)
    prearrival_housekeeping_hours = fields.Integer(
        string="Pre-arrival Housekeeping Lead (hours)", default=24
    )
    adult_age_min = fields.Integer(default=18)
    teenager_age_min = fields.Integer(default=13)
    teenager_age_max = fields.Integer(default=17)
    child_age_min = fields.Integer(default=3)
    child_age_max = fields.Integer(default=12)
    infant_age_max = fields.Integer(default=2)
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
        "Hotel code must be unique per company.",
    )
    _company_uniq = models.Constraint(
        "unique (company_id)",
        "Each Odoo company or branch can have only one hotel configuration.",
    )

    @api.depends("room_ids.active", "room_ids.is_sellable")
    def _compute_room_count(self):
        for prop in self:
            rooms = prop.room_ids.filtered("active")
            prop.room_count = len(rooms)
            prop.sellable_room_count = len(rooms.filtered("is_sellable"))

    @api.model
    def _get_default_property(self):
        """Return the private hotel configuration for the active Odoo company."""
        company = self.env.company
        prop = self.sudo().search(
            [("company_id", "=", company.id), ("active", "=", True)],
            order="id",
            limit=1,
        )
        if not prop:
            prop = self.sudo().create(
                {
                    "name": company.name,
                    "code": str(company.id),
                    "company_id": company.id,
                    "address_id": company.partner_id.id,
                    "timezone": self.env.user.tz or "Africa/Tripoli",
                }
            )
        return self.browse(prop.id)

    @api.model_create_multi
    def create(self, vals_list):
        properties = super().create(vals_list)
        properties._secure_website_gallery()
        return properties

    def write(self, values):
        result = super().write(values)
        if "website_gallery_attachment_ids" in values:
            self._secure_website_gallery()
        return result

    def _secure_website_gallery(self):
        attachments = self.mapped("website_gallery_attachment_ids")
        if attachments:
            attachments.sudo().write({"public": False})
        return True

    @api.constrains("website_gallery_attachment_ids")
    def _check_website_gallery_images(self):
        for property_rec in self:
            invalid = property_rec.website_gallery_attachment_ids.filtered(
                lambda attachment: not (attachment.mimetype or "").startswith("image/")
            )
            if invalid:
                raise ValidationError(_("The hotel website gallery accepts images only."))

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

    @api.constrains(
        "day_start_hour",
        "cancellation_grace_hours",
        "cancellation_fee_value",
        "no_show_grace_hours",
        "no_show_fee_value",
        "website_review_limit",
        "online_deposit_value",
        "online_hold_minutes",
        "prearrival_housekeeping_hours",
        "adult_age_min",
        "teenager_age_min",
        "teenager_age_max",
        "child_age_min",
        "child_age_max",
        "infant_age_max",
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
            if prop.website_review_limit < 0:
                raise ValidationError(_("The website review limit cannot be negative."))
            if prop.online_hold_minutes <= 0:
                raise ValidationError(_("The online room hold must be at least one minute."))
            if prop.prearrival_housekeeping_hours < 0:
                raise ValidationError(
                    _("The pre-arrival housekeeping lead cannot be negative.")
                )
            ages = (
                prop.adult_age_min,
                prop.teenager_age_min,
                prop.teenager_age_max,
                prop.child_age_min,
                prop.child_age_max,
                prop.infant_age_max,
            )
            if min(ages) < 0:
                raise ValidationError(_("Guest age limits cannot be negative."))
            if not (
                prop.infant_age_max < prop.child_age_min
                <= prop.child_age_max < prop.teenager_age_min
                <= prop.teenager_age_max < prop.adult_age_min
            ):
                raise ValidationError(_("Guest age ranges must be ordered and must not overlap."))
            if prop.online_deposit_value < 0:
                raise ValidationError(_("The online deposit cannot be negative."))
            if (
                prop.online_payment_policy == "percent_deposit"
                and prop.online_deposit_value > 100
            ):
                raise ValidationError(_("The online deposit percentage cannot exceed 100."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_module_uninstall(self):
        raise UserError(
            _(
                "Company hotel configurations cannot be deleted. Archive the Odoo company "
                "when the hotel is no longer active."
            )
        )
