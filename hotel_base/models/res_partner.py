from odoo import _, api, fields, models
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

    def _default_hotel_agency_from_parent(self):
        """Apply the parent agency internally without exposing protected fields."""
        for partner in self:
            protected_partner = partner.sudo()
            parent = protected_partner.parent_id
            if (
                protected_partner.is_hotel_guest
                and not protected_partner.is_company
                and not protected_partner.hotel_agency_id
                and parent
                and parent.is_hotel_agency
            ):
                super(ResPartner, protected_partner).write(
                    {"hotel_agency_id": parent.id}
                )

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        eligible_partners = partners.browse(
            partner.id
            for partner, vals in zip(partners, vals_list, strict=True)
            if not vals.get("hotel_agency_id")
        )
        eligible_partners._default_hotel_agency_from_parent()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if "parent_id" in vals:
            self._default_hotel_agency_from_parent()
        return result

    @api.onchange("parent_id", "is_hotel_guest", "is_company")
    def _onchange_parent_hotel_agency(self):
        can_access_hotel_fields = self.env.user.has_group(
            "hotel_base.group_hotel_frontdesk"
        ) or self.env.user.has_group("hotel_base.group_hotel_accountant")
        if not can_access_hotel_fields:
            return
        for partner in self:
            if (
                partner.is_hotel_guest
                and not partner.is_company
                and not partner.hotel_agency_id
                and partner.parent_id.sudo().is_hotel_agency
            ):
                partner.hotel_agency_id = partner.parent_id

    def _assign_hotel_property(self, prop):
        prop.ensure_one()
        if self.filtered(
            lambda partner: partner.company_id
            and partner.company_id != prop.company_id
        ):
            raise UserError(_("The hotel partner and property must use the same company."))
        records = self.filtered(lambda partner: not partner.company_id)
        return super(ResPartner, records).write({"company_id": prop.company_id.id})
