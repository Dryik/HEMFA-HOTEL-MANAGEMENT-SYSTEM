from odoo import SUPERUSER_ID, _, api
from odoo.exceptions import UserError


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        SELECT user_id, property_id, array_agg(id ORDER BY date_opened DESC, id DESC)
        FROM hotel_frontdesk_session
        WHERE state = 'opened'
        GROUP BY user_id, property_id
        HAVING count(*) > 1
        """
    )
    duplicate_sessions = cr.fetchall()
    if duplicate_sessions:
        details = "; ".join(
            f"cashier={user_id}, property={property_id}, sessions={session_ids}"
            for user_id, property_id, session_ids in duplicate_sessions
        )
        raise UserError(
            _(
                "Resolve duplicate open cashier sessions before upgrading: %(details)s",
                details=details,
            )
        )
    cr.execute(
        """
        UPDATE hotel_frontdesk_session
        SET active_open_key = user_id::text || ':' || property_id::text
        WHERE state = 'opened' AND active_open_key IS NULL
        """
    )
    cash_lines = env["hotel.frontdesk.session.cash"].search(
        [("journal_id", "=", False)]
    )
    for line in cash_lines:
        journal = env["account.journal"].search(
            [
                ("company_id", "=", line.session_id.property_id.company_id.id),
                ("type", "in", ("cash", "bank")),
            ],
            order="type desc, id",
            limit=1,
        )
        if journal:
            line.journal_id = journal
