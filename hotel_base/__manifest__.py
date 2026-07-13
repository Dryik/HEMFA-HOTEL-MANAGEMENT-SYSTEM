{
    "name": "Hotel Base",
    "summary": "Secure multi-property foundation for hotel operations",
    "description": """
Hotel Base is the central configuration and master-data application for the
HEMFA Hotel Management System. It organizes hotel properties, floors, room
types, rooms, amenities, guests, agencies and property-level user access in
one consistent workspace.

The application provides timezone-aware business days, operational room
states, guest identity profiles, agency relationships and role-based data
protection. It is the shared foundation used by reservations, front desk,
folios, housekeeping, maintenance, night audit, POS room charging and hotel
reporting.
""",
    "version": "19.0.3.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["base", "mail", "product", "contacts"],
    "data": [
        "security/hotel_security.xml",
        "security/hotel_record_rules.xml",
        "security/ir.model.access.csv",
        "views/hotel_property_views.xml",
        "views/hotel_floor_views.xml",
        "views/hotel_room_type_views.xml",
        "views/hotel_amenity_views.xml",
        "views/hotel_room_views.xml",
        "views/res_partner_views.xml",
        "views/res_users_views.xml",
        "views/hotel_agency_commission_views.xml",
        "views/hotel_menus.xml",
    ],
    "demo": [
        "demo/hotel_demo.xml",
    ],
    "application": True,
    "installable": True,
}
