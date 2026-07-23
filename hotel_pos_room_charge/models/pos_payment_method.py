from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    is_room_charge = fields.Boolean(
        string="Charge to Room",
        help="Settling with this method posts the order to the in-house "
        "guest's folio instead of collecting money at the POS. The "
        "order's customer must be a checked-in hotel guest.",
    )
    hotel_property_id = fields.Many2one(
        "hotel.property",
        string="Hotel Company Link",
        domain="[('company_id', '=', company_id)]",
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )

    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            "is_room_charge",
            "hotel_property_id",
        ]

    @api.onchange("is_room_charge", "company_id")
    def _onchange_room_charge_company(self):
        for method in self.filtered("is_room_charge"):
            company = method.company_id or self.env.company
            method.hotel_property_id = self.env["hotel.property"].with_company(
                company
            )._get_default_property()

    @api.constrains(
        "is_room_charge", "hotel_property_id", "receivable_account_id", "company_id"
    )
    def _check_room_charge_configuration(self):
        for method in self.filtered("is_room_charge"):
            prop = method.hotel_property_id
            if not prop or prop.company_id != method.company_id:
                raise ValidationError(
                    _("A room-charge payment method must use the active POS company.")
                )
            if not prop.room_charge_clearing_account_id or not prop.room_charge_journal_id:
                raise ValidationError(
                    _("Configure the company's room-charge clearing account and journal first.")
                )
            if method.receivable_account_id != prop.room_charge_clearing_account_id:
                raise ValidationError(
                    _("The POS intermediary account must be the company's room-charge clearing account.")
                )


class PosConfig(models.Model):
    _inherit = "pos.config"

    hotel_property_id = fields.Many2one(
        "hotel.property",
        string="Hotel Company Link",
        domain="[('company_id', '=', company_id)]",
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )

    # Do not override ``_load_pos_data_fields`` here. In Odoo 19 the core
    # pos.config implementation intentionally returns an empty list so
    # ``read([])`` loads every configuration field. Replacing that sentinel
    # with only hotel_property_id removes core fields such as use_pricelist
    # and currency_id from the POS bootstrap payload.

    @api.model
    def get_hotel_room_charge_candidates(self, config_id):
        config = self.browse(config_id).exists()
        if not config or config.company_id not in self.env.companies:
            raise ValidationError(_("The POS configuration is not available in the active company."))
        property_rec = config.hotel_property_id
        if not property_rec:
            return []
        reservations = self.env["hotel.reservation"].sudo().search(
            [
                ("property_id", "=", property_rec.id),
                ("state", "=", "checked_in"),
            ],
            order="room_id, actual_checkin desc",
        )
        return [
            {
                "id": reservation.id,
                "reservation": reservation.name,
                "guest": reservation.partner_id.name,
                "room": reservation.room_id.name,
                "room_type": reservation.room_type_id.name,
                "partner_id": reservation.partner_id.id,
            }
            for reservation in reservations
        ]

    @api.onchange("company_id", "payment_method_ids")
    def _onchange_hotel_company(self):
        for config in self:
            if config.payment_method_ids.filtered("is_room_charge"):
                company = config.company_id or self.env.company
                config.hotel_property_id = self.env["hotel.property"].with_company(
                    company
                )._get_default_property()

    @api.constrains("hotel_property_id", "company_id", "payment_method_ids")
    def _check_hotel_property_configuration(self):
        for config in self:
            room_methods = config.payment_method_ids.filtered("is_room_charge")
            if room_methods and not config.hotel_property_id:
                raise ValidationError(
                    _("The POS company could not be prepared for room charges.")
                )
            if config.hotel_property_id and config.hotel_property_id.company_id != config.company_id:
                raise ValidationError(_("The POS room-charge setup must use the same company."))
            if room_methods.filtered(
                lambda method: method.hotel_property_id != config.hotel_property_id
            ):
                raise ValidationError(
                    _("Room-charge payment methods must match the POS company.")
                )
