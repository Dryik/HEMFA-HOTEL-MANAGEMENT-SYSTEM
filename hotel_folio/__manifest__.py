{
    "name": "Hotel Folios",
    "summary": "Folio ledger, charge routing matrix, deposits, guest/entity/group invoicing",
    "version": "19.0.0.1.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_reservation", "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/hotel_folio_sequence.xml",
        "views/hotel_folio_views.xml",
        "views/hotel_reservation_views.xml",
    ],
    "installable": True,
}
