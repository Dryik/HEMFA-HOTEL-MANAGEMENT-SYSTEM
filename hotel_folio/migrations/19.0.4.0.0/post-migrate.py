from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Ensure active stays retain their remaining room revenue after retirement."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    reservations = env["hotel.reservation"].search(
        [("state", "in", ("confirmed", "checked_in"))]
    )
    reservations._ensure_stay_charge()
