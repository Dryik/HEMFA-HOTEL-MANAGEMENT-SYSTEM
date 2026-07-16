{
    "name": "Hotel Website Booking",
    "summary": "Sales-free hotel website, multi-room booking, payments, and portal",
    "version": "19.0.1.0.0",
    "category": "Hotel Management",
    "author": "HEMFA",
    "license": "OPL-1",
    "depends": [
        "website",
        "portal",
        "payment",
        "account_payment",
        "hotel_rate",
        "hotel_guest_services",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/hotel_website_booking_rules.xml",
        "data/hotel_online_booking_sequence.xml",
        "data/hotel_online_booking_cron.xml",
        "data/hotel_mail_templates.xml",
        "views/hotel_online_booking_views.xml",
        "views/hotel_company_website_views.xml",
        "views/hotel_website_templates.xml",
        "views/hotel_portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "hotel_website_booking/static/src/scss/hotel_website.scss",
        ],
    },
    "installable": True,
    "application": False,
}
