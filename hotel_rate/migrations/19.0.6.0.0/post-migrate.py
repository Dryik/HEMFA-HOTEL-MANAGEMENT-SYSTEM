from odoo import SUPERUSER_ID, api

from odoo.addons.hotel_rate.hooks import migrate_legacy_rates


def migrate(cr, version):
    """Create legacy seasonal plans and immutable nightly snapshots on upgrade."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    migrate_legacy_rates(env)
