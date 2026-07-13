from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    properties = env["hotel.property"].with_context(active_test=False).search([])
    group_xmlids = (
        "hotel_base.group_hotel_frontdesk",
        "hotel_base.group_hotel_cashier",
        "hotel_base.group_hotel_fo_supervisor",
        "hotel_base.group_hotel_housekeeping",
        "hotel_base.group_hotel_maintenance",
        "hotel_base.group_hotel_fb",
        "hotel_base.group_hotel_accountant",
        "hotel_base.group_hotel_manager",
    )
    groups = env["res.groups"].browse(
        [env.ref(xmlid).id for xmlid in group_xmlids]
    )
    users = env["res.users"].with_context(active_test=False).search(
        [("group_ids", "in", groups.ids)]
    )
    for user in users:
        if not user.hotel_property_ids:
            user.hotel_property_ids = properties.filtered(
                lambda prop: prop.company_id in user.company_ids
            )
        if not user.default_hotel_property_id and user.hotel_property_ids:
            user.default_hotel_property_id = user.hotel_property_ids.sorted("name")[:1]

    # On an upgrade, infer guest/entity property membership from existing
    # stays before the new partner record rule becomes operational.  A fresh
    # database installs hotel_base before hotel_reservation, so the table is
    # intentionally optional here.
    cr.execute("SELECT to_regclass('hotel_reservation')")
    if cr.fetchone()[0]:
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
