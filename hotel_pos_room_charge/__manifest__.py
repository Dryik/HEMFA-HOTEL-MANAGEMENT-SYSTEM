{
    "name": "POS Room Charge",
    "summary": "POS charge-to-room payment method with folio and ceiling validation",
    "version": "19.0.2.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_folio", "hotel_restricted_services", "point_of_sale"],
    "data": [
        "security/hotel_pos_security.xml",
        "views/pos_payment_method_views.xml",
    ],
    "installable": True,
}
