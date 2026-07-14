{
    "name": "Hotel Guest Services",
    "summary": "Lost-and-found, do-not-disturb, and wake-up call operations",
    "version": "19.0.4.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_reservation"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/hotel_guest_services_sequences.xml",
        "views/hotel_guest_services_views.xml",
    ],
    "installable": True,
}
