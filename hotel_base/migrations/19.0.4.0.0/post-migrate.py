from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remove retired operational modules and preserve front-desk access."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    cashier_group = env.ref(
        "hotel_base.group_hotel_cashier", raise_if_not_found=False
    )
    retired = env["ir.module.module"].search(
        [
            ("name", "in", ("hotel_frontdesk_session", "hotel_night_audit")),
            ("state", "in", ("installed", "to upgrade")),
        ]
    )
    if retired:
        retired.module_uninstall()

    if cashier_group and cashier_group.exists():
        cashier_group.unlink()
    env["ir.model.data"].search(
        [("module", "=", "hotel_base"), ("name", "=", "group_hotel_cashier")]
    ).unlink()
