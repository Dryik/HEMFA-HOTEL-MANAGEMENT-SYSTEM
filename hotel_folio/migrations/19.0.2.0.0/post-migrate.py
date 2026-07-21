from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        UPDATE hotel_folio AS folio
           SET property_id = reservation.property_id,
               reservation_state = reservation.state
          FROM hotel_reservation AS reservation
         WHERE reservation.id = folio.reservation_id
           AND (folio.property_id IS DISTINCT FROM reservation.property_id
                OR folio.reservation_state IS DISTINCT FROM reservation.state)
        """
    )
    folios = env["hotel.folio"].search([])
    lines = env["hotel.folio.line"].search([])
    for line in lines:
        values = {}
        if not line.service_date:
            values["service_date"] = line.folio_id.property_id.get_business_date(
                line.date
            )
        if line.is_posted and line.lock_state == "unlocked":
            values["lock_state"] = (
                "accounting" if line.invoice_line_id else "unlocked"
            )
        if line.invoice_line_id and not line.source_reference:
            values["source_reference"] = line.invoice_line_id.move_id.display_name
        if values:
            line.with_context(hotel_migration=True).write(values)
    lines._compute_amount()
    # Direct compute calls write stored values and also cover databases upgraded
    # from commits that introduced these fields without a versioned migration.
    folios._compute_totals()
    folios._compute_is_open()
