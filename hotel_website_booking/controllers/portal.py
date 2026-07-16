import base64
import hmac

from werkzeug.exceptions import NotFound

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class HotelCustomerPortal(CustomerPortal):
    def _portal_booking_domain(self):
        partner = request.env.user.partner_id.commercial_partner_id
        return [("partner_id.commercial_partner_id", "=", partner.id)]

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if not counters or "hotel_booking_count" in counters:
            values["hotel_booking_count"] = request.env["hotel.online.booking"].sudo().search_count(
                self._portal_booking_domain()
            )
        return values

    @http.route("/my/hotel-bookings", type="http", auth="user", website=True)
    def portal_hotel_bookings(self, **kwargs):
        values = self._prepare_portal_layout_values()
        bookings = request.env["hotel.online.booking"].sudo().search(
            self._portal_booking_domain(), order="create_date desc", limit=200
        )
        values.update(
            {
                "bookings": bookings,
                "page_name": "hotel_bookings",
            }
        )
        return request.render("hotel_website_booking.portal_my_hotel_bookings", values)

    @http.route(
        "/my/hotel-bookings/<string:token>", type="http", auth="user", website=True
    )
    def portal_hotel_booking(self, token, **kwargs):
        booking = request.env["hotel.online.booking"].sudo().search(
            [("access_token", "=", token)] + self._portal_booking_domain(), limit=1
        )
        if not booking or not hmac.compare_digest(booking.access_token, token):
            raise NotFound()
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "booking": booking,
                "page_name": "hotel_booking",
                "document_types": request.env["hotel.document.type"].sudo().search(
                    [
                        ("property_id", "=", booking.property_id.id),
                        ("active", "=", True),
                    ]
                ),
            }
        )
        return request.render("hotel_website_booking.portal_my_hotel_booking", values)

    @http.route(
        "/my/hotel-bookings/<string:token>/documents",
        type="http",
        methods=["POST"],
        auth="user",
        website=True,
    )
    def portal_hotel_document_upload(self, token, **form):
        booking = request.env["hotel.online.booking"].sudo().search(
            [("access_token", "=", token)] + self._portal_booking_domain(), limit=1
        )
        if not booking or not booking.reservation_ids:
            raise NotFound()
        upload = request.httprequest.files.get("document")
        document_type = request.env["hotel.document.type"].sudo().search(
            [
                ("id", "=", int(form.get("document_type_id") or 0)),
                ("property_id", "=", booking.property_id.id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not upload or not document_type:
            raise ValidationError(_("Select a valid document type and file."))
        allowed_types = {"application/pdf", "image/jpeg", "image/png"}
        if upload.mimetype not in allowed_types:
            raise ValidationError(_("Only PDF, JPEG, and PNG documents are accepted."))
        data = upload.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValidationError(_("Documents cannot exceed 10 MB."))
        filename = (upload.filename or "document").replace("\\", "/").rsplit("/", 1)[-1]
        attachment = request.env["ir.attachment"].sudo().create(
            {
                "name": filename[:255],
                "datas": base64.b64encode(data),
                "mimetype": upload.mimetype,
                "public": False,
            }
        )
        try:
            request.env["hotel.reservation.document"].sudo().create(
                {
                    "reservation_id": booking.reservation_ids[:1].id,
                    "document_type_id": document_type.id,
                    "attachment_id": attachment.id,
                    "expiry_date": form.get("expiry_date") or False,
                }
            )
        except (UserError, ValidationError):
            attachment.unlink()
            raise
        return request.redirect(f"/my/hotel-bookings/{token}")

    @http.route(
        "/my/hotel-documents/<int:document_id>/<string:token>",
        type="http",
        auth="user",
        website=True,
    )
    def portal_hotel_document_download(self, document_id, token, **kwargs):
        booking = request.env["hotel.online.booking"].sudo().search(
            [("access_token", "=", token)] + self._portal_booking_domain(), limit=1
        )
        document = request.env["hotel.reservation.document"].sudo().browse(document_id).exists()
        if (
            not booking
            or not document
            or document.reservation_id not in booking.reservation_ids
        ):
            raise NotFound()
        return request.env["ir.binary"].sudo()._get_stream_from(
            document.attachment_id
        ).get_response(as_attachment=True, immutable=False)
