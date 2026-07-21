from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Backfill the business-day foundation without inventing stay events."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute(
        """
        INSERT INTO hotel_property_partner_rel (partner_id, property_id)
        SELECT partner_id, property_id
          FROM hotel_reservation
         WHERE partner_id IS NOT NULL AND property_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    cr.execute(
        """
        INSERT INTO hotel_property_partner_rel (partner_id, property_id)
        SELECT agency_id, property_id
          FROM hotel_reservation
         WHERE agency_id IS NOT NULL AND property_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    # Older reservations could rely only on room_id.  Keep their explicit
    # room-type inventory key consistent before recomputing availability data.
    cr.execute(
        """
        UPDATE hotel_reservation AS reservation
           SET room_type_id = room.room_type_id
          FROM hotel_room AS room
         WHERE room.id = reservation.room_id
           AND reservation.room_type_id IS NULL
        """
    )

    reservations = env["hotel.reservation"].with_context(
        active_test=False, hotel_migration=True
    ).search([])
    reservations._compute_business_dates()
    reservations._compute_nights()
    reservations._compute_amount_total()

    # A future confirmed booking is inventory, not physical occupancy.  The
    # legacy "reserved" room state is therefore cleared, while actual in-house
    # stays remain the only records that mark a room occupied.  We deliberately
    # do not manufacture actual_checkin/actual_checkout timestamps.
    cr.execute(
        """
        UPDATE hotel_room
           SET occupancy_state = 'vacant'
         WHERE occupancy_state = 'reserved'
        """
    )
    cr.execute(
        """
        UPDATE hotel_room AS room
           SET occupancy_state = 'occupied'
         WHERE EXISTS (
               SELECT 1
                 FROM hotel_reservation AS reservation
                WHERE reservation.room_id = room.id
                  AND reservation.state = 'checked_in'
         )
        """
    )
