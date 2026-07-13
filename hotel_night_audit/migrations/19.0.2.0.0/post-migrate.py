def migrate(cr, version):
    cr.execute(
        """
        UPDATE hotel_night_audit_line AS line
           SET room_id = reservation.room_id,
               partner_id = reservation.partner_id
          FROM hotel_reservation AS reservation
         WHERE reservation.id = line.reservation_id
           AND (line.room_id IS DISTINCT FROM reservation.room_id
                OR line.partner_id IS DISTINCT FROM reservation.partner_id)
        """
    )
