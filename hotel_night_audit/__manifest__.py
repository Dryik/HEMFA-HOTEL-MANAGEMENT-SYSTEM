{
    "name": "Hotel Night Audit",
    "summary": "Daily rollover: room-night posting, no-shows, occupancy snapshot, audit report",
    "version": "19.0.2.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_frontdesk_session"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/hotel_night_audit_sequence.xml",
        "wizard/night_audit_reversal_wizard_views.xml",
        "views/hotel_night_audit_views.xml",
    ],
    "installable": True,
}
