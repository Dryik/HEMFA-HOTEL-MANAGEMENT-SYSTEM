import hmac
from datetime import timedelta

from werkzeug.exceptions import NotFound

from odoo import Command, _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


class HotelWebsiteController(http.Controller):
    @staticmethod
    def _as_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _property():
        website = request.website
        return request.env["hotel.property"].sudo().search(
            [
                ("company_id", "=", website.company_id.id),
                ("website_id", "=", website.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ],
            limit=1,
        )

    @staticmethod
    def _pricelist(property_rec, pricelist_id=None):
        base_domain = [
            ("active", "=", True),
            ("hotel_website_published", "=", True),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", property_rec.company_id.id),
        ]
        pricelist = request.env["product.pricelist"].sudo()
        pricelist_id = HotelWebsiteController._as_int(pricelist_id)
        if pricelist_id:
            pricelist = pricelist.search(
                [("id", "=", pricelist_id), *base_domain], limit=1
            )
        pricelist = pricelist or request.env["product.pricelist"].sudo().search(
            base_domain, limit=1
        )
        if not pricelist:
            raise NotFound()
        return pricelist

    @staticmethod
    def _stay_datetimes(property_rec, checkin=None, checkout=None):
        today = property_rec.get_business_date()
        arrival = fields.Date.to_date(checkin) if checkin else today + timedelta(days=1)
        departure = fields.Date.to_date(checkout) if checkout else arrival + timedelta(days=1)
        if departure <= arrival:
            raise ValidationError(_("Departure must be after arrival."))
        if arrival < today:
            raise ValidationError(_("Arrival cannot be in the past."))
        checkin_date, _unused = property_rec.get_business_day_bounds(arrival)
        checkout_date, _unused = property_rec.get_business_day_bounds(departure)
        return arrival, departure, checkin_date, checkout_date

    @staticmethod
    def _booking_from_token(token, require_website=True):
        booking = request.env["hotel.online.booking"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        if (
            not booking
            or not hmac.compare_digest(booking.access_token, token)
            or (require_website and booking.website_id != request.website)
        ):
            raise NotFound()
        return booking

    def _room_values(self, **params):
        property_rec = self._property()
        if not property_rec:
            raise NotFound()
        error = params.get("error")
        try:
            arrival, departure, checkin_date, checkout_date = self._stay_datetimes(
                property_rec, params.get("checkin"), params.get("checkout")
            )
        except (ValueError, ValidationError) as exception:
            arrival, departure, checkin_date, checkout_date = self._stay_datetimes(
                property_rec
            )
            error = str(exception)
        adults = max(self._as_int(params.get("adults"), 1), 1)
        teenagers = max(self._as_int(params.get("teenagers")), 0)
        children = max(self._as_int(params.get("children")), 0)
        infants = max(self._as_int(params.get("infants")), 0)
        nationality_id = self._as_int(params.get("nationality_id"))
        pricelist = self._pricelist(property_rec, params.get("pricelist_id"))
        domain = [
            ("active", "=", True),
            ("property_id", "=", property_rec.id),
            ("website_published", "=", True),
            ("room_ids.is_sellable", "=", True),
        ]
        room_type_id = self._as_int(params.get("room_type_id"))
        if room_type_id:
            domain.append(("id", "=", room_type_id))
        meal_required = str(params.get("meal") or "").lower() in {"1", "true", "on"}
        if meal_required:
            domain.extend(
                [
                    "|",
                    "&",
                    ("complimentary_service_ids.is_meal", "=", True),
                    ("complimentary_service_ids.website_published", "=", True),
                    "&",
                    ("optional_service_ids.is_meal", "=", True),
                    ("optional_service_ids.website_published", "=", True),
                ]
            )
        amenity_ids = [
            int(value)
            for value in request.httprequest.args.getlist("amenity_id")
            if str(value).isdigit()
        ]
        if amenity_ids:
            domain.append(("amenity_ids", "in", amenity_ids))
        room_types = request.env["hotel.room.type"].sudo().search(domain)
        room_cards = []
        for room_type in room_types:
            if (
                adults > room_type.capacity_adults
                or teenagers > room_type.capacity_teenagers
                or children > room_type.capacity_children
                or infants > room_type.capacity_infants
            ):
                continue
            rooms = request.env["hotel.availability.service"].sudo().get_available_rooms(
                property_rec.id,
                checkin_date,
                checkout_date,
                room_type.id,
                website_only=True,
            )
            if not rooms:
                continue
            quote = request.env["hotel.rate.quote"].sudo().with_company(
                property_rec.company_id
            ).quote(
                property_rec.id,
                room_type.id,
                checkin_date,
                checkout_date,
                pricelist_id=pricelist.id,
                adults=adults,
                teenagers=teenagers,
                children=children,
                infants=infants,
                nationality_id=nationality_id,
            )
            min_price = self._as_float(params.get("min_price"))
            max_price = self._as_float(params.get("max_price"))
            if min_price and quote["amount_total"] < min_price:
                continue
            if max_price and quote["amount_total"] > max_price:
                continue
            room_cards.append(
                {
                    "room_type": room_type,
                    "available_qty": len(rooms),
                    "quote": quote,
                }
            )
        services = request.env["hotel.service"].sudo().search(
            [
                ("property_id", "=", property_rec.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ]
        )
        service_cards = [
            {
                "service": service,
                "price": service.currency_id._convert(
                    service.default_price if service.is_paid else 0.0,
                    pricelist.currency_id,
                    property_rec.company_id,
                    arrival,
                ),
            }
            for service in services
        ]
        return {
            "property": property_rec,
            "room_cards": room_cards,
            "amenities": request.env["hotel.amenity"].sudo().search([]),
            "room_type_options": request.env["hotel.room.type"].sudo().search(
                [
                    ("property_id", "=", property_rec.id),
                    ("active", "=", True),
                    ("website_published", "=", True),
                ]
            ),
            "service_cards": service_cards,
            "countries": request.env["res.country"].sudo().search([]),
            "pricelists": request.env["product.pricelist"].sudo().search(
                [
                    ("active", "=", True),
                    ("hotel_website_published", "=", True),
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "=", property_rec.company_id.id),
                ]
            ),
            "pricelist": pricelist,
            "arrival": arrival,
            "departure": departure,
            "adults": adults,
            "teenagers": teenagers,
            "children": children,
            "infants": infants,
            "nationality_id": nationality_id,
            "selected_amenity_ids": amenity_ids,
            "selected_room_type_id": room_type_id,
            "meal_required": meal_required,
            "error": error,
        }

    @http.route("/hotel", type="http", auth="public", website=True, sitemap=True)
    def hotel_home(self, **kwargs):
        property_rec = self._property()
        if not property_rec:
            raise NotFound()
        reviews = request.env["hotel.guest.rating"].sudo().search(
            [("property_id", "=", property_rec.id), ("state", "=", "approved")],
            limit=property_rec.website_review_limit,
        )
        room_types = request.env["hotel.room.type"].sudo().search(
            [
                ("property_id", "=", property_rec.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ],
            limit=6,
        )
        return request.render(
            "hotel_website_booking.hotel_home",
            {"property": property_rec, "reviews": reviews, "room_types": room_types},
        )

    @http.route("/hotel/rooms", type="http", auth="public", website=True, sitemap=True)
    def hotel_rooms(self, **params):
        return request.render(
            "hotel_website_booking.hotel_rooms", self._room_values(**params)
        )

    @http.route(
        "/hotel/room/<int:room_type_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_room_detail(self, room_type_id, **params):
        property_rec = self._property()
        room_type = request.env["hotel.room.type"].sudo().search(
            [
                ("id", "=", room_type_id),
                ("property_id", "=", property_rec.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ],
            limit=1,
        )
        if not room_type:
            raise NotFound()
        return request.render(
            "hotel_website_booking.hotel_room_detail",
            {"property": property_rec, "room_type": room_type},
        )

    @http.route("/hotel/book", type="http", methods=["POST"], auth="public", website=True)
    def hotel_book(self, **form):
        property_rec = self._property()
        if not property_rec:
            raise NotFound()
        try:
            with request.env.cr.savepoint():
                _arrival, _departure, checkin_date, checkout_date = self._stay_datetimes(
                    property_rec, form.get("checkin"), form.get("checkout")
                )
                pricelist = self._pricelist(property_rec, form.get("pricelist_id"))
                published_types = request.env["hotel.room.type"].sudo().search(
                    [
                        ("property_id", "=", property_rec.id),
                        ("active", "=", True),
                        ("website_published", "=", True),
                    ]
                )
                room_commands = []
                for room_type in published_types:
                    quantity = int(form.get(f"room_qty_{room_type.id}") or 0)
                    if quantity > 0:
                        room_commands.append(
                            Command.create(
                                {
                                    "room_type_id": room_type.id,
                                    "quantity": quantity,
                                    "adults": max(int(form.get("adults") or 1), 1),
                                    "teenagers": max(int(form.get("teenagers") or 0), 0),
                                    "children": max(int(form.get("children") or 0), 0),
                                    "infants": max(int(form.get("infants") or 0), 0),
                                }
                            )
                        )
                if not room_commands:
                    raise ValidationError(_("Select at least one available room."))
                if request.env.user._is_public():
                    partner = request.env["res.partner"].sudo().create(
                        {
                            "name": (form.get("name") or "").strip(),
                            "email": (form.get("email") or "").strip(),
                            "phone": (form.get("phone") or "").strip(),
                            "country_id": int(form.get("country_id") or 0) or False,
                            "guest_nationality_id": int(form.get("nationality_id") or 0) or False,
                            "is_hotel_guest": True,
                            "company_id": property_rec.company_id.id,
                        }
                    )
                else:
                    partner = request.env.user.partner_id.sudo()
                    partner.write(
                        {
                            "is_hotel_guest": True,
                            "guest_nationality_id": int(form.get("nationality_id") or 0) or False,
                        }
                    )
                if not partner.name or not partner.email:
                    raise ValidationError(_("Guest name and email are required."))
                service_commands = []
                services = request.env["hotel.service"].sudo().search(
                    [
                        ("property_id", "=", property_rec.id),
                        ("active", "=", True),
                        ("website_published", "=", True),
                    ]
                )
                for service in services:
                    quantity = float(form.get(f"service_qty_{service.id}") or 0)
                    if quantity > 0:
                        service_commands.append(
                            Command.create({"service_id": service.id, "quantity": quantity})
                        )
                booking = request.env["hotel.online.booking"].sudo().with_company(
                    property_rec.company_id
                ).create(
                    {
                        "website_id": request.website.id,
                        "property_id": property_rec.id,
                        "partner_id": partner.id,
                        "checkin_date": checkin_date,
                        "checkout_date": checkout_date,
                        "adults": max(int(form.get("adults") or 1), 1),
                        "teenagers": max(int(form.get("teenagers") or 0), 0),
                        "children": max(int(form.get("children") or 0), 0),
                        "infants": max(int(form.get("infants") or 0), 0),
                        "nationality_id": int(form.get("nationality_id") or 0) or False,
                        "pricelist_id": pricelist.id,
                        "currency_id": pricelist.currency_id.id,
                        "line_ids": room_commands,
                        "service_line_ids": service_commands,
                        "customer_note": form.get("customer_note"),
                    }
                )
                booking.action_submit()
            return request.redirect(f"/hotel/booking/{booking.access_token}")
        except (ValueError, UserError, ValidationError) as exception:
            values = self._room_values(**form)
            values["error"] = str(exception)
            return request.render("hotel_website_booking.hotel_rooms", values)

    @http.route(
        "/hotel/booking/<string:token>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_booking_status(self, token, **kwargs):
        booking = self._booking_from_token(token)
        return request.render(
            "hotel_website_booking.hotel_booking_status",
            {
                "booking": booking,
                "can_cancel": booking.state
                in ("pending_review", "held", "payment_pending", "payment_exception", "confirmed")
                and booking.checkin_date > fields.Datetime.now(),
            },
        )

    @http.route(
        "/hotel/booking/<string:token>/cancel",
        type="http",
        methods=["POST"],
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_booking_cancel(self, token, **kwargs):
        booking = self._booking_from_token(token)
        booking.action_cancel_online()
        return request.redirect(f"/hotel/booking/{token}")

    @http.route(
        "/hotel/rating/<string:token>",
        type="http",
        methods=["GET", "POST"],
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_rating(self, token, **form):
        rating = request.env["hotel.guest.rating"].sudo().search(
            [("access_token", "=", token)], limit=1
        )
        property_rec = self._property()
        if (
            not rating
            or not hmac.compare_digest(rating.access_token, token)
            or rating.property_id != property_rec
        ):
            raise NotFound()
        error = False
        if request.httprequest.method == "POST":
            try:
                rating._submit_public_feedback(
                    {
                        "rating": int(form.get("rating") or 0),
                        "cleanliness_rating": int(form.get("cleanliness_rating") or 0),
                        "service_rating": int(form.get("service_rating") or 0),
                        "value_rating": int(form.get("value_rating") or 0),
                        "comments": form.get("comments"),
                    }
                )
            except (ValueError, UserError, ValidationError) as exception:
                error = str(exception)
        return request.render(
            "hotel_website_booking.hotel_rating", {"rating": rating, "error": error}
        )

    @http.route(
        ["/hotel/facilities", "/hotel/gallery", "/hotel/policies", "/hotel/contact"],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
    )
    def hotel_content_page(self, **kwargs):
        property_rec = self._property()
        if not property_rec:
            raise NotFound()
        page = request.httprequest.path.rsplit("/", 1)[-1]
        return request.render(
            f"hotel_website_booking.hotel_{page}",
            {
                "property": property_rec,
                "amenities": request.env["hotel.amenity"].sudo().search([]),
                "services": request.env["hotel.service"].sudo().search(
                    [
                        ("property_id", "=", property_rec.id),
                        ("active", "=", True),
                        ("website_published", "=", True),
                    ]
                ),
                "room_types": request.env["hotel.room.type"].sudo().search(
                    [
                        ("property_id", "=", property_rec.id),
                        ("active", "=", True),
                        ("website_published", "=", True),
                    ]
                ),
            },
        )

    @http.route(
        "/hotel/gallery/image/<int:attachment_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_gallery_image(self, attachment_id, **kwargs):
        property_rec = self._property()
        attachment = request.env["ir.attachment"].sudo().browse(attachment_id).exists()
        allowed = request.env["hotel.room.type"].sudo().search_count(
            [
                ("property_id", "=", property_rec.id),
                ("active", "=", True),
                ("website_published", "=", True),
                ("gallery_attachment_ids", "in", attachment.ids),
            ]
        )
        allowed = allowed or attachment in property_rec.website_gallery_attachment_ids
        if not attachment or not allowed or not attachment.mimetype.startswith("image/"):
            raise NotFound()
        return request.env["ir.binary"].sudo()._get_stream_from(attachment).get_response(
            as_attachment=False, immutable=True
        )

    @http.route(
        "/hotel/media/property/<int:property_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_property_media(self, property_id, **kwargs):
        property_rec = self._property()
        if not property_rec or property_rec.id != property_id:
            raise NotFound()
        return request.env["ir.binary"].sudo()._get_image_stream_from(
            property_rec, "website_banner"
        ).get_response(as_attachment=False, immutable=False)

    @http.route(
        "/hotel/media/room-type/<int:room_type_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_room_type_media(self, room_type_id, **kwargs):
        property_rec = self._property()
        if not property_rec:
            raise NotFound()
        room_type = request.env["hotel.room.type"].sudo().search(
            [
                ("id", "=", room_type_id),
                ("property_id", "=", property_rec.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ],
            limit=1,
        )
        if not room_type:
            raise NotFound()
        return request.env["ir.binary"].sudo()._get_image_stream_from(
            room_type, "website_image"
        ).get_response(as_attachment=False, immutable=False)

    @http.route(
        "/hotel/media/service/<int:service_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def hotel_service_media(self, service_id, **kwargs):
        property_rec = self._property()
        if not property_rec:
            raise NotFound()
        service = request.env["hotel.service"].sudo().search(
            [
                ("id", "=", service_id),
                ("property_id", "=", property_rec.id),
                ("active", "=", True),
                ("website_published", "=", True),
            ],
            limit=1,
        )
        if not service:
            raise NotFound()
        return request.env["ir.binary"].sudo()._get_image_stream_from(
            service, "image"
        ).get_response(as_attachment=False, immutable=False)
