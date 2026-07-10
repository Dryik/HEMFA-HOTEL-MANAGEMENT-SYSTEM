{
    "name": "Hotel Night Audit",
    "summary": "Daily rollover: room-night posting, no-shows, occupancy snapshot, audit report",
    "version": "19.0.0.1.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_folio"],
    "data": [
        "security/ir.model.access.csv",
        "data/hotel_night_audit_sequence.xml",
        "views/hotel_night_audit_views.xml",
    ],
    "installable": True,
}
