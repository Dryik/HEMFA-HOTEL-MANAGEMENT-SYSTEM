from odoo import _, api, models
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
    ):
        prop = self.env["hotel.property"].browse(property_id).exists()
        if not prop or not checkin_date or not checkout_date:
            return self.env["hotel.room"]
        room_domain = [
            ("property_id", "=", prop.id),
            ("is_sellable", "=", True),
        ]
        if room_type_id:
            room_domain.append(("room_type_id", "=", room_type_id))
        rooms = self.env["hotel.room"].search(room_domain)
        reservation_domain = [
            ("property_id", "=", prop.id),
            ("room_id", "in", rooms.ids),
            ("state", "in", ("confirmed", "checked_in")),
            ("checkin_date", "<", checkout_date),
            ("checkout_date", ">", checkin_date),
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
