from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelAvailabilityService(models.AbstractModel):
    _name = "hotel.availability.service"
    _description = "Shared Hotel Room Availability Service"

    @api.model
    def get_available_rooms(
        self,
        property_id,
        checkin_date,
        checkout_date,
        room_type_id=None,
        exclude_reservation_id=None,
        website_only=False,
    ):
        prop = self.env["hotel.property"].browse(property_id).exists()
        if not prop or not checkin_date or not checkout_date:
            return self.env["hotel.room"]
        expired_holds = self.env["hotel.reservation"].sudo().search(
            [
                ("property_id", "=", prop.id),
                ("state", "=", "pending_payment"),
                ("hold_expires_at", "<=", fields.Datetime.now()),
            ]
        )
        if expired_holds:
            expired_holds._action_expire_payment_hold()
        room_domain = [
            ("property_id", "=", prop.id),
            ("is_sellable", "=", True),
        ]
        if room_type_id:
            room_domain.append(("room_type_id", "=", room_type_id))
        if website_only:
            room_domain.append(("website_published", "=", True))
        rooms = self.env["hotel.room"].search(room_domain)
        reservation_domain = [
            ("property_id", "=", prop.id),
            ("room_id", "in", rooms.ids),
            ("checkin_date", "<", checkout_date),
            ("checkout_date", ">", checkin_date),
            ("state", "in", ("pending_payment", "confirmed", "checked_in")),
        ]
        if exclude_reservation_id:
            reservation_domain.append(("id", "!=", exclude_reservation_id))
        blocked_rooms = self.env["hotel.reservation"].search(
            reservation_domain
        ).mapped("room_id")
        return rooms - blocked_rooms

    @api.model
    def assert_room_available(
        self, room, checkin_date, checkout_date, exclude_reservation_id=None
    ):
        if not room.is_sellable:
            raise ValidationError(
                _("Room %(room)s is not sellable.", room=room.display_name)
            )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (7719, room.id))
        # Force a write/write conflict under Odoo's REPEATABLE READ isolation.
        # If another transaction confirmed the same room after this request's
        # snapshot, Odoo retries this transaction and availability is checked
        # again against a fresh snapshot.  This also protects installations
        # where btree_gist cannot be enabled for the exclusion constraint.
        self.env.cr.execute("UPDATE hotel_room SET id = id WHERE id = %s", [room.id])
        available = self.get_available_rooms(
            room.property_id.id,
            checkin_date,
            checkout_date,
            room.room_type_id.id,
            exclude_reservation_id=exclude_reservation_id,
        )
        if room not in available:
            raise ValidationError(
                _(
                    "Room %(room)s is not available between %(checkin)s and %(checkout)s.",
                    room=room.display_name,
                    checkin=checkin_date,
                    checkout=checkout_date,
                )
            )
        return True

    @api.model
    def assign_rooms(
        self,
        property_id,
        checkin_date,
        checkout_date,
        requests,
        website_only=False,
    ):
        """Atomically assign physical rooms for several room-type quantities.

        ``requests`` is a list of dictionaries containing ``room_type_id`` and
        ``quantity``.  Locks are held until the surrounding transaction ends;
        callers must create their blocking reservations in that transaction.
        """
        assignments = []
        requested_room_ids = set()
        for request_values in requests:
            room_type_id = int(request_values.get("room_type_id") or 0)
            quantity = int(request_values.get("quantity") or 0)
            if not room_type_id or quantity <= 0:
                raise ValidationError(_("Every room request needs a room type and quantity."))
            available = self.get_available_rooms(
                property_id,
                checkin_date,
                checkout_date,
                room_type_id,
                website_only=website_only,
            ).filtered(lambda room: room.id not in requested_room_ids)
            if len(available) < quantity:
                room_type = self.env["hotel.room.type"].browse(room_type_id)
                raise ValidationError(
                    _(
                        "Only %(available)s %(room_type)s room(s) remain available; "
                        "%(requested)s were requested.",
                        available=len(available),
                        room_type=room_type.display_name,
                        requested=quantity,
                    )
                )
            selected = available[:quantity]
            for room in selected:
                requested_room_ids.add(room.id)
                assignments.append(
                    {"room_type_id": room_type_id, "room_id": room.id}
                )
        # A single global lock order prevents cross-room-type deadlocks when
        # two multi-room baskets request their room types in a different order.
        selected_rooms = self.env["hotel.room"].browse(
            [assignment["room_id"] for assignment in assignments]
        )
        for room in selected_rooms.sorted("id"):
            self.assert_room_available(room, checkin_date, checkout_date)
        return assignments
