{
    "name": "Hotel Reservations",
    "summary": "Reservation lifecycle, Gantt tape chart, calendar, availability",
    "version": "19.0.3.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_base", "web_gantt"],
    "data": [
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/hotel_reservation_extended_sequences.xml",
        "views/hotel_reservation_views.xml",
        "views/hotel_reservation_extended_views.xml",
    ],
    "demo": [
        "demo/hotel_reservation_demo.xml",
    ],
    "installable": True,
}
