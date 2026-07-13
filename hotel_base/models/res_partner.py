from odoo import Command, _, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    """Guest identity and agency/entity flags.

    Identity fields mirror the legacy registration form so front desk
    loses nothing at cutover. Stay-specific data (coming from, heading
    to, trip number, accommodation type) lives on the reservation, not
    here — it changes per stay.
    """

    _inherit = "res.partner"

    is_hotel_guest = fields.Boolean(
        index=True,
        groups="hotel_base.group_hotel_frontdesk,hotel_base.group_hotel_accountant",
    )
    is_hotel_agency = fields.Boolean(
        string="Is Agency / Entity",
        index=True,
        groups="hotel_base.group_hotel_frontdesk,hotel_base.group_hotel_accountant",
        help="Travel agency, company or government entity (جهة) that can "
        "be billed for its guests and hold advance balances.",
    )
    hotel_property_ids = fields.Many2many(
        "hotel.property",
        "hotel_property_partner_rel",
        "partner_id",
        "property_id",
        string="Hotel Properties",
        default=lambda self: self.env.user.default_hotel_property_id.ids,
        readonly=True,
        help="Properties where this guest or entity is authorized for hotel use.",
    )

    guest_gender = fields.Selection(
        [("male", "Male"), ("female", "Female")],
        string="Gender",
        groups="hotel_base.group_hotel_frontdesk",
    )
    guest_nationality_id = fields.Many2one(
        "res.country",
        string="Nationality",
        groups="hotel_base.group_hotel_frontdesk",
        help="Drives the LYD vs foreign-currency pricing rule "
        "(hotel_rate).",
    )
    guest_birthdate = fields.Date(
        string="Date of Birth", groups="hotel_base.group_hotel_frontdesk"
    )
    guest_birthplace = fields.Char(
        string="Place of Birth", groups="hotel_base.group_hotel_frontdesk"
    )
    guest_profession = fields.Char(
        string="Profession", groups="hotel_base.group_hotel_frontdesk"
    )
    guest_national_number = fields.Char(
        string="National Number",
        groups="hotel_base.group_hotel_frontdesk",
        help="Libyan national number (الرقم الوطني).",
    )
    guest_id_type = fields.Selection(
        [
            ("passport", "Passport"),
            ("national_id", "National ID"),
            ("family_book", "Family Book"),
            ("driving_license", "Driving License"),
            ("other", "Other"),
        ],
        string="ID Type",
        default="passport",
        groups="hotel_base.group_hotel_frontdesk",
    )
    guest_id_number = fields.Char(
        string="ID Number", groups="hotel_base.group_hotel_frontdesk"
    )
    guest_id_expiry = fields.Date(
        string="ID Expiry", groups="hotel_base.group_hotel_frontdesk"
    )
    hotel_agency_id = fields.Many2one(
        "res.partner",
        string="Default Agency / Entity",
        domain=[("is_hotel_agency", "=", True)],
        groups="hotel_base.group_hotel_frontdesk,hotel_base.group_hotel_accountant",
        help="Entity this guest is usually registered under. The "
        "reservation can override it per stay.",
    )

    def _assign_hotel_property(self, prop):
        prop.ensure_one()
        if self.filtered(
            lambda partner: partner.company_id
            and partner.company_id != prop.company_id
        ):
            raise UserError(_("The hotel partner and property must use the same company."))
        records = self.filtered(lambda partner: prop not in partner.hotel_property_ids)
        if records:
            return super(ResPartner, records).write(
                {"hotel_property_ids": [Command.link(prop.id)]}
            )
        return True

    def write(self, vals):
        if "hotel_property_ids" in vals and not self.env.user.has_group(
            "base.group_system"
        ):
            raise UserError(
                _("Hotel partner property membership is assigned by hotel workflows.")
            )
        return super().write(vals)
