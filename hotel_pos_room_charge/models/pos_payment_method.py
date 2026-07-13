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
        string="Hotel Property",
        domain="[('company_id', '=', company_id)]",
    )

    @api.constrains(
        "is_room_charge", "hotel_property_id", "receivable_account_id", "company_id"
    )
    def _check_room_charge_configuration(self):
        for method in self.filtered("is_room_charge"):
            prop = method.hotel_property_id
            if not prop or prop.company_id != method.company_id:
                raise ValidationError(
                    _("A room-charge payment method requires a property in the same company.")
                )
            if not prop.room_charge_clearing_account_id or not prop.room_charge_journal_id:
                raise ValidationError(
                    _("Configure the property's room-charge clearing account and journal first.")
                )
            if method.receivable_account_id != prop.room_charge_clearing_account_id:
                raise ValidationError(
                    _("The POS intermediary account must be the property's room-charge clearing account.")
                )


class PosConfig(models.Model):
    _inherit = "pos.config"

    hotel_property_id = fields.Many2one(
        "hotel.property",
        string="Hotel Property",
        domain="[('company_id', '=', company_id)]",
    )

    @api.constrains("hotel_property_id", "company_id", "payment_method_ids")
    def _check_hotel_property_configuration(self):
        for config in self:
            room_methods = config.payment_method_ids.filtered("is_room_charge")
            if room_methods and not config.hotel_property_id:
                raise ValidationError(
                    _("Select a hotel property when the POS accepts room charges.")
                )
            if config.hotel_property_id and config.hotel_property_id.company_id != config.company_id:
                raise ValidationError(_("The POS and hotel property must use the same company."))
            if room_methods.filtered(
                lambda method: method.hotel_property_id != config.hotel_property_id
            ):
                raise ValidationError(
                    _("Room-charge payment methods must match the POS hotel property.")
                )
