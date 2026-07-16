def migrate(cr, version):
    """Seed the current cancellation event without inventing older history."""
    cr.execute(
        """
        UPDATE hotel_reservation
           SET cancelled_at = write_date
         WHERE state = 'cancelled'
           AND cancelled_at IS NULL
        """
    )
