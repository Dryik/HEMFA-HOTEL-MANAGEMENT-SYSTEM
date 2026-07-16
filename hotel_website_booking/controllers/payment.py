import hmac

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.controllers.portal import PaymentPortal


class HotelPaymentPortal(PaymentPortal):
    @staticmethod
    def _booking(token):
        booking = request.env["hotel.online.booking"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        if (
            not booking
            or not hmac.compare_digest(booking.access_token, token)
            or booking.website_id != request.website
        ):
            raise NotFound()
        return booking

    @http.route(
        "/hotel/booking/<string:token>/pay",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_booking_pay(self, token, **kwargs):
        booking = self._booking(token)
        if booking.state not in ("held", "payment_pending"):
            return request.redirect(f"/hotel/booking/{token}")
        access_token = payment_utils.generate_access_token(
            booking.partner_id.id, booking.amount_due_online, booking.currency_id.id
        )
        return self.payment_pay(
            reference=booking.name,
            amount=str(booking.amount_due_online),
            currency_id=str(booking.currency_id.id),
            partner_id=str(booking.partner_id.id),
            company_id=str(booking.company_id.id),
            access_token=access_token,
            hotel_booking_token=token,
        )

    def _get_extra_payment_form_values(self, hotel_booking_token=None, **kwargs):
        values = super()._get_extra_payment_form_values(
            hotel_booking_token=hotel_booking_token, **kwargs
        )
        if hotel_booking_token:
            booking = self._booking(hotel_booking_token)
            values.update(
                {
                    "hotel_booking": booking,
                    "submit_button_label": _("Pay and Confirm"),
                    "transaction_route": f"/hotel/payment/transaction/{hotel_booking_token}",
                    "landing_route": f"/hotel/booking/{hotel_booking_token}",
                }
            )
        return values

    @http.route(
        "/hotel/payment/transaction/<string:token>",
        type="jsonrpc",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_payment_transaction(
        self, token, amount, currency_id, partner_id, access_token, **kwargs
    ):
        booking = self._booking(token)
        amount = float(amount)
        currency_id = int(currency_id)
        partner_id = int(partner_id)
        if not payment_utils.check_access_token(
            access_token, partner_id, amount, currency_id
        ):
            raise Forbidden()
        payment_partner = request.env["res.partner"].sudo().browse(partner_id).exists()
        if (
            booking.state not in ("held", "payment_pending")
            or not payment_partner
            or payment_partner.commercial_partner_id
            != booking.partner_id.commercial_partner_id
            or currency_id != booking.currency_id.id
            or booking.currency_id.compare_amounts(amount, booking.amount_due_online) != 0
        ):
            raise ValidationError(_("The hotel booking payment details are no longer valid."))
        self._validate_transaction_kwargs(kwargs, additional_allowed_keys=("reference_prefix",))
        custom_values = dict(kwargs.pop("custom_create_values", {}) or {})
        custom_values["hotel_online_booking_id"] = booking.id
        transaction = self._create_transaction(
            amount=amount,
            currency_id=currency_id,
            partner_id=partner_id,
            custom_create_values=custom_values,
            **kwargs,
        )
        self._update_landing_route(transaction, access_token)
        return transaction._get_processing_values()
