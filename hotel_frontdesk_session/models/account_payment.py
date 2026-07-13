from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = "account.payment"

    hotel_frontdesk_session_id = fields.Many2one(
        "hotel.frontdesk.session",
        string="Cashier Session",
        index=True,
        copy=False,
        domain="[('property_id', '=', hotel_property_id), ('state', '=', 'opened')]",
    )

    @api.constrains("hotel_frontdesk_session_id", "hotel_property_id", "company_id")
    def _check_hotel_session_consistency(self):
        for payment in self.filtered("hotel_frontdesk_session_id"):
            session = payment.hotel_frontdesk_session_id
            if session.state != "opened" and payment.state == "draft":
                raise ValidationError(_("A draft payment cannot be linked to a closed session."))
            if payment.hotel_property_id != session.property_id:
                raise ValidationError(_("Payment and cashier session must use the same property."))
            if payment.company_id != session.property_id.company_id:
                raise ValidationError(_("Payment and cashier session must use the same company."))

    def write(self, vals):
        if "hotel_frontdesk_session_id" in vals:
            if self.mapped("hotel_frontdesk_session_id").filtered(
                lambda session: session.state == "closed"
            ):
                raise UserError(_("A payment cannot be moved out of a closed cashier session."))
            target = self.env["hotel.frontdesk.session"].browse(
                vals.get("hotel_frontdesk_session_id")
            )
            if target and target.state == "closed":
                raise UserError(_("A payment cannot be linked to a closed cashier session."))
        return super().write(vals)
