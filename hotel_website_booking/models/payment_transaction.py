from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    hotel_online_booking_id = fields.Many2one(
        "hotel.online.booking",
        string="Hotel Online Booking",
        readonly=True,
        copy=False,
        index=True,
        ondelete="restrict",
    )

    @api.constrains("hotel_online_booking_id", "company_id", "partner_id", "currency_id")
    def _check_hotel_booking_transaction(self):
        for transaction in self.filtered("hotel_online_booking_id"):
            booking = transaction.hotel_online_booking_id
            if transaction.company_id != booking.company_id:
                raise ValidationError(_("The payment transaction must use the hotel company."))
            if transaction.partner_id.commercial_partner_id != booking.partner_id.commercial_partner_id:
                raise ValidationError(_("The payment transaction must belong to the booking guest."))
            if transaction.currency_id != booking.currency_id:
                raise ValidationError(_("The transaction and booking currencies must match."))

    def _create_payment(self, **extra_create_values):
        self.ensure_one()
        if self.hotel_online_booking_id:
            booking = self.hotel_online_booking_id
            extra_create_values.update(
                {
                    "partner_id": booking.partner_id.id,
                    "hotel_property_id": booking.property_id.id,
                    "hotel_payment_purpose": "guest_deposit",
                    "hotel_online_booking_id": booking.id,
                    "hotel_reservation_group_id": booking.group_id.id,
                }
            )
        return super()._create_payment(**extra_create_values)

    def _post_process(self):
        result = super()._post_process()
        for transaction in self.filtered(
            lambda item: item.state == "done" and item.hotel_online_booking_id
        ):
            transaction.hotel_online_booking_id._confirm_paid_transaction(transaction)
        return result

    def _log_message_on_linked_documents(self, message):
        super()._log_message_on_linked_documents(message)
        for transaction in self.filtered("hotel_online_booking_id"):
            transaction.hotel_online_booking_id.message_post(body=message)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    hotel_online_booking_id = fields.Many2one(
        "hotel.online.booking", readonly=True, copy=False, ondelete="restrict", index=True
    )
    hotel_reservation_group_id = fields.Many2one(
        "hotel.reservation.group", readonly=True, copy=False, ondelete="restrict", index=True
    )

    @api.constrains(
        "hotel_online_booking_id",
        "hotel_reservation_group_id",
        "hotel_property_id",
        "company_id",
    )
    def _check_online_booking_payment(self):
        for payment in self.filtered("hotel_online_booking_id"):
            booking = payment.hotel_online_booking_id
            if payment.company_id != booking.company_id or payment.hotel_property_id != booking.property_id:
                raise ValidationError(_("The online payment must use the booking hotel company."))
            if payment.hotel_reservation_group_id != booking.group_id:
                raise ValidationError(_("The payment reservation group must match the booking."))

    def write(self, values):
        if {"hotel_online_booking_id", "hotel_reservation_group_id"}.intersection(values) and self.filtered(
            lambda payment: payment.state != "draft"
        ):
            raise UserError(_("Posted online hotel payment references are immutable."))
        return super().write(values)


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        result = super().action_post()
        allocation_model = self.env["hotel.payment.allocation"]
        allocations = allocation_model
        for move in self.filtered(lambda item: item.is_invoice(include_receipts=True)):
            domain = []
            if move.hotel_folio_id:
                domain.append(("folio_id", "=", move.hotel_folio_id.id))
            if move.hotel_reservation_group_id:
                group_domain = (
                    "online_booking_id.group_id",
                    "=",
                    move.hotel_reservation_group_id.id,
                )
                domain = ["|", *domain, group_domain] if domain else [group_domain]
            if domain:
                allocations |= allocation_model.search(domain)
        allocations._reconcile_posted_documents()
        return result
