from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestHotelBase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor 1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Test Double",
                "base_price": 100.0,
                "property_id": cls.property.id,
            }
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

    def test_inventory_history_is_archive_only(self):
        room = self.env["hotel.room"].create(
            {
                "name": "Archive 101",
                "floor_id": self.floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        with self.assertRaises(UserError):
            room.unlink()
        with self.assertRaises(UserError):
            self.room_type.write({"active": False})
        with self.assertRaises(UserError):
            self.floor.write({"active": False})

        room.write({"retirement_reason": "Renovation", "active": False})
        self.room_type.write({"retirement_reason": "Retired category", "active": False})
        self.floor.write({"retirement_reason": "Closed wing", "active": False})

        self.assertTrue(room.retired_at)
        self.assertTrue(self.room_type.retired_at)
        self.assertTrue(self.floor.retired_at)
        self.assertFalse(self.room_type.product_id.active)
        with self.assertRaises(UserError):
            self.room_type.unlink()
        with self.assertRaises(UserError):
            self.floor.unlink()

    @mute_logger("odoo.sql_db")
    def test_room_number_unique_per_property(self):
        self.env["hotel.room"].create(
            {
                "name": "202",
                "floor_id": self.floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        with self.assertRaises(Exception), self.env.cr.savepoint():
            self.env["hotel.room"].create(
                {
                    "name": "202",
                    "floor_id": self.floor.id,
                    "room_type_id": self.room_type.id,
                }
            )
            self.env["hotel.room"].flush_model()
