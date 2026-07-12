{
    "name": "Hotel Reports",
    "summary": "Front-desk daily reports: arrivals, departures, in-house, security list",
    "version": "19.0.1.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    # hotel_folio / hotel_housekeeping stay as deps for the upcoming
    # debtor and discrepancy reports of Phase 5.
    "depends": ["hotel_folio", "hotel_housekeeping"],
    "data": [
        "security/ir.model.access.csv",
        "report/hotel_report_templates.xml",
        "wizard/hotel_report_wizard_views.xml",
    ],
    "installable": True,
}
