{
    "name": "Hotel Front Desk Workspace",
    "summary": "Operational dashboard, room board, and inventory planning tape",
    "version": "19.0.3.1.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": [
        "hotel_reservation",
        "hotel_folio",
        "hotel_frontdesk_session",
        "hotel_night_audit",
        "hotel_housekeeping",
        "hotel_maintenance",
        "hotel_guest_services",
        "hotel_reports",
        "web",
    ],
    "data": [
        "views/hotel_board_actions.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hotel_board/static/src/**/*",
        ],
        "web.assets_unit_tests": [
            "hotel_board/static/tests/**/*.test.js",
        ],
    },
    "installable": True,
}
