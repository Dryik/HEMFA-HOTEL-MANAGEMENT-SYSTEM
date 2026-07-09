{
    "name": "Hotel Front Desk Dashboard",
    "summary": "Live KPI dashboard and room board for the front desk",
    "version": "19.0.1.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": ["hotel_reservation", "web"],
    "data": [
        "views/hotel_board_actions.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "hotel_board/static/src/**/*",
        ],
    },
    "installable": True,
}
