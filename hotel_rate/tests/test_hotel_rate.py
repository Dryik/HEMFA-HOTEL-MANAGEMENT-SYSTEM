from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelRate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"]._get_default_property()
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor 1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {
                "name": "Rate Double Room",
                "base_price": 200.0,
                "property_id": cls.property.id,
            }
        )
        cls.room1 = cls.env["hotel.room"].create(
            {
                "name": "R101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.room2 = cls.env["hotel.room"].create(
            {
                "name": "R102",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.libyan_country = cls.env["res.country"].search([("code", "=", "LY")], limit=1)
        if not cls.libyan_country:
            cls.libyan_country = cls.env["res.country"].create(
                {"name": "Libya", "code": "LY"}
            )
        cls.us_country = cls.env["res.country"].search([("code", "=", "US")], limit=1)
        if not cls.us_country:
            cls.us_country = cls.env["res.country"].create(
                {"name": "United States", "code": "US"}
            )

        cls.guest_libyan = cls.env["res.partner"].create(
            {
                "name": "Libyan Guest",
                "is_hotel_guest": True,
                "guest_nationality_id": cls.libyan_country.id,
            }
        )
        cls.guest_foreigner = cls.env["res.partner"].create(
            {
                "name": "Foreign Guest",
                "is_hotel_guest": True,
                "guest_nationality_id": cls.us_country.id,
            }
        )

        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def _reservation(self, partner, room, offset_days=0, nights=2, state="draft"):
        checkin = self.checkin + timedelta(days=offset_days)
        return self.env["hotel.reservation"].create(
            {
                "partner_id": partner.id,
                "property_id": self.property.id,
                "room_id": room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": checkin,
                "checkout_date": checkin + timedelta(days=nights),
                "state": state,
            }
        )

    def test_default_base_price(self):
        res = self._reservation(self.guest_libyan, self.room1)
        self.assertEqual(res.rate_night, 200.0)

    def test_seasonal_rate_rule(self):
        # Create seasonal rate rule of 250 LYD/USD
        start_date = fields.Date.today()
        end_date = start_date + timedelta(days=5)
        self.env["hotel.rate.rule"].create(
            {
                "name": "High Season Rule",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": end_date,
                "rate_price": 250.0,
                "guest_type": "all",
            }
        )

        res = self._reservation(self.guest_libyan, self.room1)
        self.assertEqual(res.rate_night, 250.0)

    def test_rate_rule_overlapping_rejected(self):
        start_date = fields.Date.today()
        end_date = start_date + timedelta(days=5)
        self.env["hotel.rate.rule"].create(
            {
                "name": "Rule 1",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": end_date,
                "rate_price": 250.0,
                "guest_type": "all",
            }
        )
        with self.assertRaises(ValidationError):
            self.env["hotel.rate.rule"].create(
                {
                    "name": "Overlapping Rule",
                    "property_id": self.property.id,
                    "room_type_id": self.room_type.id,
                    "date_start": start_date + timedelta(days=1),
                    "date_end": end_date + timedelta(days=1),
                    "rate_price": 300.0,
                    "guest_type": "all",
                }
            )

    def test_nationality_rate_rules(self):
        start_date = fields.Date.today()
        end_date = start_date + timedelta(days=5)
        
        # Local rule
        self.env["hotel.rate.rule"].create(
            {
                "name": "Local Guest Discount",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": end_date,
                "rate_price": 150.0,
                "guest_type": "local",
            }
        )

        # Foreigner rule
        self.env["hotel.rate.rule"].create(
            {
                "name": "Foreigner Stay Rate",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": end_date,
                "rate_price": 300.0,
                "guest_type": "foreign",
            }
        )

        res_local = self._reservation(self.guest_libyan, self.room1)
        res_foreign = self._reservation(self.guest_foreigner, self.room2)
        
        self.assertEqual(res_local.rate_night, 150.0)
        self.assertEqual(res_foreign.rate_night, 300.0)

    def test_occupancy_band_multiplier(self):
        # Create occupancy band: 50% to 100% occupancy multiplies price by 1.5
        band = self.env["hotel.rate.occupancy.band"].create(
            {
                "name": "High Occupancy Band",
                "property_id": self.property.id,
                "min_occupancy": 50,
                "max_occupancy": 100,
                "multiplier": 1.5,
            }
        )
        self.assertAlmostEqual(band.adjustment_pct, 50.0)

        # Confirm first reservation to occupy room 1 (making occupancy 50% because we have 2 sellable rooms)
        res1 = self._reservation(self.guest_libyan, self.room1, state="draft")
        res1.action_confirm()

        # Create second reservation (will look up occupancy rate for the check-in date)
        # 1 occupied out of 2 rooms is 50.0%, which falls in [50, 100], multiplying rate by 1.5
        res2 = self._reservation(self.guest_foreigner, self.room2)
        self.assertEqual(res2.rate_night, 300.0) # 200 * 1.5 = 300.0

    def test_rate_lock(self):
        res = self._reservation(self.guest_libyan, self.room1)
        self.assertEqual(res.rate_night, 200.0)
        self.assertFalse(res.rate_locked)

        # Confirm lock
        res.action_confirm()
        self.assertTrue(res.rate_locked)
        with self.assertRaises(UserError):
            res.write({"rate_locked": False})

        # Create a seasonal rate rule of 250.0
        start_date = fields.Date.today()
        end_date = start_date + timedelta(days=5)
        self.env["hotel.rate.rule"].create(
            {
                "name": "High Season Rule",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": end_date,
                "rate_price": 250.0,
                "guest_type": "all",
            }
        )

        # Compute rate check again. Rate should remain 200.0 because it's locked.
        res._compute_rate_night()
        self.assertEqual(res.rate_night, 200.0)
