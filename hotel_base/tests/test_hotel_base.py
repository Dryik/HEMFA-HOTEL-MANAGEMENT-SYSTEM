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

    def test_company_create_does_not_trip_hotel_property_validation(self):
        # A plain company create must not push empty hotel operational values
        # (e.g. online_hold_minutes = 0) into the auto-created property.
        company = self.env["res.company"].create({"name": "Fresh Hotel Co"})
        company.flush_recordset()
        self.assertEqual(
            company.hotel_property_config_id.online_hold_minutes,
            15,
            "Auto-created property should keep its valid default hold.",
        )
        # Renaming a company must also stay clear of the constraint.
        company.write({"name": "Fresh Hotel Co (Renamed)"})
        company.flush_recordset()
        self.assertEqual(
            company.hotel_property_config_id.name, "Fresh Hotel Co (Renamed)"
        )

    def test_company_create_applies_explicit_hotel_settings(self):
        company = self.env["res.company"].create(
            {"name": "Custom Hotel Co", "hotel_online_hold_minutes": 30}
        )
        company.flush_recordset()
        self.assertEqual(company.hotel_property_config_id.online_hold_minutes, 30)

    def test_guest_defaults_agency_from_parent_on_create(self):
        agency = self.env["res.partner"].create(
            {"name": "Default Parent Agency", "is_hotel_agency": True}
        )
        guest = self.env["res.partner"].create(
            {
                "name": "Agency Guest",
                "is_hotel_guest": True,
                "parent_id": agency.id,
            }
        )
        self.assertEqual(guest.hotel_agency_id, agency)

    def test_guest_keeps_explicit_agency_on_create(self):
        parent_agency = self.env["res.partner"].create(
            {"name": "Parent Agency", "is_hotel_agency": True}
        )
        explicit_agency = self.env["res.partner"].create(
            {"name": "Explicit Agency", "is_hotel_agency": True}
        )
        guest = self.env["res.partner"].create(
            {
                "name": "Explicit Agency Guest",
                "is_hotel_guest": True,
                "parent_id": parent_agency.id,
                "hotel_agency_id": explicit_agency.id,
            }
        )
        self.assertEqual(guest.hotel_agency_id, explicit_agency)
        second_parent = self.env["res.partner"].create(
            {"name": "Second Parent Agency", "is_hotel_agency": True}
        )
        guest.parent_id = second_parent
        self.assertEqual(guest.hotel_agency_id, explicit_agency)

    def test_guest_does_not_default_non_agency_parent(self):
        company = self.env["res.partner"].create(
            {"name": "Ordinary Parent Company", "is_company": True}
        )
        guest = self.env["res.partner"].create(
            {
                "name": "Ordinary Company Guest",
                "is_hotel_guest": True,
                "parent_id": company.id,
            }
        )
        self.assertFalse(guest.hotel_agency_id)

    def test_guest_defaults_agency_when_parent_changes(self):
        agency = self.env["res.partner"].create(
            {"name": "Changed Parent Agency", "is_hotel_agency": True}
        )
        guest = self.env["res.partner"].create(
            {"name": "Changed Parent Guest", "is_hotel_guest": True}
        )
        guest.parent_id = agency
        self.assertEqual(guest.hotel_agency_id, agency)

    def test_parent_agency_onchange_defaults_before_save(self):
        agency = self.env["res.partner"].create(
            {"name": "Onchange Parent Agency", "is_hotel_agency": True}
        )
        guest = self.env["res.partner"].new(
            {
                "name": "Onchange Guest",
                "is_hotel_guest": True,
                "parent_id": agency.id,
            }
        )
        guest._onchange_parent_hotel_agency()
        self.assertEqual(guest.hotel_agency_id, agency)
