{
    "name": "Hotel Guest Services",
    "summary": "Guest operations, allotted services, documents, and ratings",
    "version": "19.0.5.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_folio"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/hotel_guest_services_sequences.xml",
        "data/hotel_commercial_sequence.xml",
        "views/hotel_guest_services_views.xml",
        "views/hotel_commercial_views.xml",
    ],
    "installable": True,
}
