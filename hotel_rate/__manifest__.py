{
    "name": "Hotel Rates",
    "summary": "Seasonal rates, occupancy bands, nationality currency rule, 12:00-12:00 business day, rate lock",
    "version": "19.0.4.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_reservation", "product"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "views/hotel_rate_views.xml",
        "views/hotel_reservation_views.xml",
    ],
    "installable": True,
}
