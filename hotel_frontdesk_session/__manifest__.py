{
    "name": "Front Desk Cashier Sessions",
    "summary": "Cashier shift sessions, multi-currency cash counts, shift-close report",
    "version": "19.0.3.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_folio"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/hotel_frontdesk_session_sequence.xml",
        "wizard/hotel_cashier_payment_wizard_views.xml",
        "views/hotel_frontdesk_session_views.xml",
    ],
    "installable": True,
}
