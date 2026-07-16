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

    def test_booking_source_uses_native_pricelist(self):
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Direct Hotel Rate",
                "currency_id": self.property.company_id.currency_id.id,
                "company_id": self.property.company_id.id,
            }
        )
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "1_product",
                "product_tmpl_id": self.room_type.product_id.product_tmpl_id.id,
                "compute_price": "fixed",
                "fixed_price": 175.0,
            }
        )
        source = self.env["hotel.booking.source"].create(
            {
                "name": "Direct",
                "property_id": self.property.id,
                "source": "direct",
                "pricelist_id": pricelist.id,
            }
        )

        reservation = self._reservation(self.guest_libyan, self.room1)

        self.assertEqual(reservation.booking_source_config_id, source)
        self.assertEqual(reservation.pricelist_id, pricelist)
        self.assertEqual(reservation.rate_night, 175.0)

    def test_guest_pricelist_overrides_booking_source_default(self):
        source_pricelist = self.env["product.pricelist"].create(
            {
                "name": "Source Rate",
                "currency_id": self.property.company_id.currency_id.id,
            }
        )
        guest_pricelist = self.env["product.pricelist"].create(
            {
                "name": "Guest Contract Rate",
                "currency_id": self.property.company_id.currency_id.id,
            }
        )
        self.env["hotel.booking.source"].create(
            {
                "name": "Direct",
                "property_id": self.property.id,
                "source": "direct",
                "pricelist_id": source_pricelist.id,
            }
        )
        self.guest_libyan.with_company(
            self.property.company_id
        ).specific_property_product_pricelist = guest_pricelist

        reservation = self._reservation(self.guest_libyan, self.room1)

        self.assertEqual(reservation.pricelist_id, guest_pricelist)

    def test_hotel_pricelist_percentage_respects_plan_and_weekday(self):
        start_date = self.property.get_business_date(self.checkin)
        plan = self.env["hotel.seasonal.pricing"].create(
            {
                "name": "Weekday Offer",
                "property_id": self.property.id,
                "date_start": start_date,
                "date_end": start_date + timedelta(days=1),
            }
        )
        plan.action_activate()
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Hotel Nightly Adjustment",
                "currency_id": self.property.company_id.currency_id.id,
            }
        )
        weekday = self.env["hotel.rate.weekday"].search(
            [("code", "=", str(start_date.weekday()))], limit=1
        )
        item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "1_product",
                "product_tmpl_id": self.room_type.product_id.product_tmpl_id.id,
                "compute_price": "percentage",
                "percent_price": 10.0,
                "base": "hotel_rate",
                "hotel_seasonal_pricing_id": plan.id,
                "hotel_weekday_ids": [(6, 0, weekday.ids)],
            }
        )

        quote = self.env["hotel.rate.quote"].quote(
            self.property.id,
            self.room_type.id,
            self.checkin,
            self.checkin + timedelta(days=2),
            pricelist_id=pricelist.id,
        )

        self.assertEqual(quote["nights"][0]["pricelist_item_id"], item.id)
        self.assertEqual(quote["nights"][0]["room_amount"], 180.0)
        self.assertFalse(quote["nights"][1]["pricelist_item_id"])
        self.assertEqual(quote["amount_untaxed"], 380.0)

    def test_extra_guest_supplement_is_snapshotted_and_locked(self):
        self.room_type.write({"capacity_adults": 3, "base_adults": 1})
        self.env["hotel.guest.supplement"].create(
            {
                "name": "Extra Adult",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "guest_category": "adult",
                "charge_type": "fixed",
                "value": 25.0,
            }
        )
        reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest_libyan.id,
                "property_id": self.property.id,
                "room_id": self.room1.id,
                "room_type_id": self.room_type.id,
                "checkin_date": self.checkin,
                "checkout_date": self.checkin + timedelta(days=1),
                "adults": 3,
            }
        )

        reservation.action_confirm()

        self.assertTrue(reservation.rate_locked)
        self.assertEqual(len(reservation.rate_line_ids), 1)
        self.assertEqual(reservation.rate_line_ids.supplement_amount, 50.0)
        self.assertEqual(reservation.rate_line_ids.amount_untaxed, 250.0)
        self.assertEqual(
            reservation.rate_line_ids.supplement_trace[0]["extra_guest_count"],
            2,
        )

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

    def test_disjoint_weekday_rate_rules_can_share_a_seasonal_range(self):
        start_date = self.property.get_business_date(self.checkin)
        weekdays = self.env["hotel.rate.weekday"].search(
            [
                (
                    "code",
                    "in",
                    [
                        str(start_date.weekday()),
                        str((start_date + timedelta(days=1)).weekday()),
                    ],
                )
            ]
        )
        weekday_by_code = {weekday.code: weekday for weekday in weekdays}
        first = self.env["hotel.rate.rule"].create(
            {
                "name": "First Weekday Rate",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": start_date + timedelta(days=1),
                "weekday_ids": [(6, 0, weekday_by_code[str(start_date.weekday())].ids)],
                "rate_price": 210.0,
                "guest_type": "all",
            }
        )
        second = self.env["hotel.rate.rule"].create(
            {
                "name": "Second Weekday Rate",
                "property_id": self.property.id,
                "room_type_id": self.room_type.id,
                "date_start": start_date,
                "date_end": start_date + timedelta(days=1),
                "weekday_ids": [
                    (
                        6,
                        0,
                        weekday_by_code[
                            str((start_date + timedelta(days=1)).weekday())
                        ].ids,
                    )
                ],
                "rate_price": 230.0,
                "guest_type": "all",
            }
        )

        quote = self.env["hotel.rate.quote"].quote(
            self.property.id,
            self.room_type.id,
            self.checkin,
            self.checkin + timedelta(days=2),
        )

        self.assertEqual(
            [night["hotel_rate_rule_id"] for night in quote["nights"]],
            [first.id, second.id],
        )
        self.assertEqual(quote["amount_untaxed"], 440.0)

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

    def test_room_move_supersedes_cached_rate_snapshots(self):
        reservation = self._reservation(self.guest_libyan, self.room1)
        # Prime the relation before confirmation to reproduce the stale-cache
        # path that previously collided with the active-night unique index.
        self.assertFalse(reservation.rate_line_ids)
        reservation.action_confirm()
        original_lines = self.env["hotel.reservation.rate.line"].search(
            [
                ("reservation_id", "=", reservation.id),
                ("superseded", "=", False),
                ("reversal_of_id", "=", False),
            ]
        )
        self.assertEqual(len(original_lines), 2)

        amendment = self.env["hotel.reservation.amendment"].create(
            {
                "reservation_id": reservation.id,
                "amendment_type": "room_move",
                "new_room_id": self.room2.id,
                "reason": "Move to a quieter room",
            }
        )
        amendment.action_apply()

        active_lines = self.env["hotel.reservation.rate.line"].search(
            [
                ("reservation_id", "=", reservation.id),
                ("superseded", "=", False),
                ("reversal_of_id", "=", False),
            ]
        )
        reversal_lines = self.env["hotel.reservation.rate.line"].search(
            [
                ("reservation_id", "=", reservation.id),
                ("reversal_of_id", "in", original_lines.ids),
            ]
        )
        self.assertEqual(len(active_lines), 2)
        self.assertEqual(len(reversal_lines), 2)
        self.assertTrue(all(original_lines.mapped("superseded")))
        self.assertEqual(active_lines.mapped("amendment_id"), amendment)
