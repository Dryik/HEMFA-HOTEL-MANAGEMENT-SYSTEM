{
    "name": "Hotel Housekeeping",
    "summary": "Cleaning tasks, dirty/clean/inspected flow, discrepancy report",
    "version": "19.0.2.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_reservation"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/hotel_housekeeping_views.xml",
        "wizard/hotel_housekeeping_discrepancy_views.xml",
        "views/hotel_housekeeping_menus.xml",
    ],
    "installable": True,
}
