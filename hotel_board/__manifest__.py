{
    "name": "Hotel Front Desk Workspace",
    "summary": "Operational dashboard, room board, and inventory planning tape",
    "version": "19.0.6.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": [
        "hotel_reservation",
        "hotel_folio",
        "hotel_housekeeping",
        "hotel_maintenance",
        "hotel_guest_services",
        "hotel_reports",
        "hotel_website_booking",
        "web",
    ],
    "data": [
        "views/hotel_board_actions.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hotel_board/static/src/shared/frontdesk_workspace.scss",
            "hotel_board/static/src/**/*",
            ("remove", "hotel_board/static/src/**/*.dark.scss"),
        ],
        # Dark-mode bundle recompiles every SCSS with the dark $o-* palette;
        # these files only override the hex-based custom properties.
        "web.assets_web_dark": [
            "hotel_board/static/src/**/*.dark.scss",
        ],
        "web.assets_unit_tests": [
            "hotel_board/static/tests/**/*.test.js",
        ],
    },
    "installable": True,
}
