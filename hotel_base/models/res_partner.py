from odoo import fields, models


class ResPartner(models.Model):
    """Guest identity and agency/entity flags.

    Identity fields mirror the legacy registration form so front desk
    loses nothing at cutover. Stay-specific data (coming from, heading
    to, trip number, accommodation type) lives on the reservation, not
    here — it changes per stay.
    """

    _inherit = "res.partner"

    is_hotel_guest = fields.Boolean(index=True)
    is_hotel_agency = fields.Boolean(
        string="Is Agency / Entity",
        index=True,
        help="Travel agency, company or government entity (جهة) that can "
        "be billed for its guests and hold advance balances.",
    )

    guest_gender = fields.Selection(
        [("male", "Male"), ("female", "Female")], string="Gender"
    )
    guest_nationality_id = fields.Many2one(
        "res.country",
        string="Nationality",
        help="Drives the LYD vs foreign-currency pricing rule "
        "(hotel_rate).",
    )
    guest_birthdate = fields.Date(string="Date of Birth")
    guest_birthplace = fields.Char(string="Place of Birth")
    guest_profession = fields.Char(string="Profession")
    guest_national_number = fields.Char(
        string="National Number",
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
    )
    guest_id_number = fields.Char(string="ID Number")
    guest_id_expiry = fields.Date(string="ID Expiry")
    hotel_agency_id = fields.Many2one(
        "res.partner",
        string="Default Agency / Entity",
        domain=[("is_hotel_agency", "=", True)],
        help="Entity this guest is usually registered under. The "
        "reservation can override it per stay.",
    )
