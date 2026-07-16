from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestHotelWebsiteHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.property.website_id = cls.env["website"].search(
            [("company_id", "=", cls.property.company_id.id)], limit=1
        )
        cls.property.write(
            {
                "website_description": "HTTP test hotel",
                "website_policy": "HTTP test policy",
                "online_payment_policy": "manual",
            }
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "HTTP Floor", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "HTTP Room Type",
                "property_id": cls.property.id,
                "website_published": True,
            }
        )
        cls.env["hotel.room"].create(
            {
                "name": "HTTP-101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
                "website_published": True,
            }
        )
        cls.env["hotel.document.type"].create(
            {
                "name": "HTTP Passport",
                "property_id": cls.property.id,
                "required_for_website": True,
            }
        )
        cls.env["product.pricelist"].create(
            {
                "name": "HTTP Hotel Pricelist",
                "currency_id": cls.property.company_id.currency_id.id,
                "company_id": cls.property.company_id.id,
                "hotel_website_published": True,
            }
        )
        cls.property.website_published = True

    def test_public_hotel_home_uses_current_website_company(self):
        response = self.url_open("/hotel")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.property.name, response.text)

    def test_invalid_booking_token_does_not_disclose_records(self):
        response = self.url_open("/hotel/booking/not-a-valid-token")
        self.assertEqual(response.status_code, 404)
