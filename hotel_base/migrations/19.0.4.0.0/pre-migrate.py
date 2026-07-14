from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Move former session operators to the standard Front Desk role."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cashier_group = env.ref(
        "hotel_base.group_hotel_cashier", raise_if_not_found=False
    )
    frontdesk_group = env.ref("hotel_base.group_hotel_frontdesk")
    if cashier_group:
        for user in cashier_group.user_ids:
            user.write({"group_ids": [(4, frontdesk_group.id)]})
