def migrate(cr, version):
    """Preserve the rate already agreed for every non-draft historical stay."""
    cr.execute(
        """
        UPDATE hotel_reservation
           SET rate_locked = TRUE
         WHERE state IN ('confirmed', 'checked_in', 'checked_out')
           AND rate_locked IS NOT TRUE
        """
    )
