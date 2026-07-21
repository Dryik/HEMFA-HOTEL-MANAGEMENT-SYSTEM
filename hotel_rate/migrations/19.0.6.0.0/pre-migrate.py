def migrate(cr, version):
    """Replace the legacy hard unique constraint with the versioned-rate index."""
    cr.execute(
        """
        ALTER TABLE hotel_reservation_rate_line
        DROP CONSTRAINT IF EXISTS
            hotel_reservation_rate_line_reservation_date_unique
        """
    )
