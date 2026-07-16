from odoo import api, fields, models


class HotelReservation(models.Model):
    _inherit = "hotel.reservation"

    prearrival_sent_at = fields.Datetime(readonly=True, copy=False)

    def _send_hotel_communication(self, xmlid):
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if template:
            for reservation in self.filtered(lambda item: item.partner_id.email):
                template.sudo().send_mail(reservation.id, force_send=False)
        return True

    def action_send_prearrival(self):
        reservations = self.filtered(
            lambda reservation: not reservation.prearrival_sent_at
            and reservation.partner_id.email
        )
        reservations._send_hotel_communication(
            "hotel_website_booking.mail_template_prearrival"
        )
        super(HotelReservation, reservations).write(
            {"prearrival_sent_at": fields.Datetime.now()}
        )
        return True

    def action_send_voucher(self):
        return self._send_hotel_communication(
            "hotel_website_booking.mail_template_reservation_voucher"
        )

    def action_confirm(self):
        to_notify = self.filtered(lambda item: item.state in ("draft", "pending_payment"))
        result = super().action_confirm()
        to_notify._send_hotel_communication(
            "hotel_website_booking.mail_template_reservation_voucher"
        )
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self._send_hotel_communication(
            "hotel_website_booking.mail_template_reservation_cancellation"
        )
        return result

    def action_check_out(self):
        result = super().action_check_out()
        self._send_hotel_communication(
            "hotel_website_booking.mail_template_checkout"
        )
        self._send_hotel_communication(
            "hotel_website_booking.mail_template_feedback_request"
        )
        return result


class HotelReservationAmendment(models.Model):
    _inherit = "hotel.reservation.amendment"

    def action_apply(self):
        room_moves = self.filtered(
            lambda amendment: amendment.state == "draft"
            and amendment.amendment_type == "room_move"
        )
        result = super().action_apply()
        room_moves.mapped("reservation_id")._send_hotel_communication(
            "hotel_website_booking.mail_template_room_exchange"
        )
        return result


class HotelOnlineBookingPrearrivalCron(models.Model):
    _inherit = "hotel.online.booking"

    @api.model
    def _cron_send_prearrival(self):
        now = fields.Datetime.now()
        for property_rec in self.env["hotel.property"].search([("active", "=", True)]):
            horizon = fields.Datetime.add(
                now, hours=property_rec.prearrival_housekeeping_hours
            )
            reservations = self.env["hotel.reservation"].search(
                [
                    ("property_id", "=", property_rec.id),
                    ("state", "=", "confirmed"),
                    ("prearrival_sent_at", "=", False),
                    ("checkin_date", ">", now),
                    ("checkin_date", "<=", horizon),
                ]
            )
            reservations.action_send_prearrival()
        return True
