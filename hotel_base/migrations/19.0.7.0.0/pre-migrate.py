def migrate(cr, version):
    """Restore the valid default for legacy company-form hold values."""
    cr.execute(
        """
        UPDATE hotel_property
           SET online_hold_minutes = 15
         WHERE online_hold_minutes IS NULL
            OR online_hold_minutes <= 0
        """
    )
