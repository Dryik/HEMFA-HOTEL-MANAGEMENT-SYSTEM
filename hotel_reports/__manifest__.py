{
    "name": "Hotel Reports",
    "summary": "Bilingual operational, finance, POS, and folio reports",
    "version": "19.0.4.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_housekeeping", "hotel_pos_room_charge"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "report/hotel_report_templates.xml",
        "wizard/hotel_report_wizard_views.xml",
    ],
    "installable": True,
}
