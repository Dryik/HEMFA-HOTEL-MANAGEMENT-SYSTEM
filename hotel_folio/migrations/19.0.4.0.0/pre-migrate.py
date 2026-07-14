def migrate(cr, version):
    """Release legacy daily-workflow locks before removing the selection value."""
    cr.execute(
        """
        UPDATE hotel_folio_line
           SET lock_state = CASE
                   WHEN invoice_line_id IS NOT NULL OR accounting_move_id IS NOT NULL
                       THEN 'accounting'
                   ELSE 'unlocked'
               END,
               is_posted = CASE
                   WHEN invoice_line_id IS NOT NULL OR accounting_move_id IS NOT NULL
                       THEN TRUE
                   ELSE FALSE
               END
         WHERE lock_state = 'night_audit'
        """
    )
