from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestHotelBase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Test Hotel", "code": "TST"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor 1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Test Double", "base_price": 100.0}
        )

    def test_room_type_creates_service_product(self):
        self.assertTrue(self.room_type.product_id)
        self.assertEqual(self.room_type.product_id.type, "service")
        self.assertEqual(self.room_type.product_id.list_price, 100.0)

    def test_base_price_syncs_to_product(self):
        self.room_type.base_price = 130.0
        self.assertEqual(self.room_type.product_id.list_price, 130.0)

    def test_sellable_room_counts(self):
        room = self.env["hotel.room"].create(
            {
                "name": "101",
                "floor_id": self.floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        self.assertTrue(room.is_sellable)
        self.assertEqual(self.property.sellable_room_count, 1)

        room.out_of_order = True
        self.assertFalse(room.is_sellable)
        self.assertEqual(self.property.room_count, 1)
        self.assertEqual(self.property.sellable_room_count, 0)

        room.out_of_order = False
        room.admin_use = True
        self.assertFalse(room.is_sellable)

    def test_room_number_unique_per_property(self):
        self.env["hotel.room"].create(
            {
                "name": "202",
                "floor_id": self.floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        with self.assertRaises(Exception):
            self.env["hotel.room"].create(
                {
                    "name": "202",
                    "floor_id": self.floor.id,
                    "room_type_id": self.room_type.id,
                }
            )
