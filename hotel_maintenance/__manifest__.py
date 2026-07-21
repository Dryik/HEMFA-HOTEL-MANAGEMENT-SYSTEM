{
    "name": "Hotel Maintenance",
    "summary": "Guest/staff maintenance workflow with room out-of-order blocking",
    "version": "19.0.4.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_base"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/hotel_maintenance_sequence.xml",
        "views/hotel_maintenance_views.xml",
    ],
    "installable": True,
}
