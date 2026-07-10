from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelFolio(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Folio Test Hotel", "code": "FTH"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor F1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Folio Suite", "base_price": 400.0}
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "R201",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "Guest Mitchell", "is_hotel_guest": True}
        )
        cls.agency = cls.env["res.partner"].create(
            {"name": "Agency Libya Travel", "is_hotel_agency": True}
        )

        # Create product categories
        cls.room_service_categ = cls.env["product.category"].create(
            {"name": "Room Service"}
        )
        cls.other_categ = cls.env["product.category"].create(
            {"name": "Other Services"}
        )

        # Create products
        cls.burger = cls.env["product.product"].create(
            {
                "name": "Burger",
                "type": "consu",
                "list_price": 15.0,
                "categ_id": cls.room_service_categ.id,
            }
        )
        cls.laundry = cls.env["product.product"].create(
            {
                "name": "Laundry Service",
                "type": "service",
                "list_price": 10.0,
                "categ_id": cls.other_categ.id,
            }
        )

        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def _reservation(self, use_agency=False):
        return self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "agency_id": self.agency.id if use_agency else False,
                "property_id": self.property.id,
                "room_id": self.room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": self.checkin,
                "checkout_date": self.checkin + timedelta(days=2),
                "state": "draft",
            }
        )

    def test_folio_auto_creation(self):
        res = self._reservation()
        self.assertEqual(res.folio_count, 0)
        res.action_confirm()
        self.assertEqual(res.folio_count, 1)
        
        folio = res.folio_ids[0]
        self.assertTrue(folio.name.startswith("FOLIO/"))
        self.assertEqual(folio.partner_id, self.guest)

    def test_add_charges(self):
        res = self._reservation()
        res.action_confirm()
        folio = res.folio_ids[0]
        
        line1 = folio.add_charge(self.burger, qty=2.0)
        self.assertEqual(line1.amount, 30.0)
        self.assertEqual(line1.payee_partner_id, self.guest)
        self.assertEqual(folio.amount_total, 30.0)

    def test_routing_rules(self):
        # Create a routing rule: route room service to the agency
        self.env["hotel.folio.routing.rule"].create(
            {
                "name": "Route Room Service to Agency",
                "property_id": self.property.id,
                "category_id": self.room_service_categ.id,
                "routing_type": "agency",
                "active": True,
            }
        )

        res = self._reservation(use_agency=True)
        res.action_confirm()
        folio = res.folio_ids[0]

        # Add room service charge (burger) -> should go to agency
        line_routed = folio.add_charge(self.burger, qty=1.0)
        self.assertEqual(line_routed.payee_partner_id, self.agency)

        # Add other category charge (laundry) -> should stay on guest
        line_guest = folio.add_charge(self.laundry, qty=1.0)
        self.assertEqual(line_guest.payee_partner_id, self.guest)

    def test_invoicing(self):
        res = self._reservation()
        res.action_confirm()
        folio = res.folio_ids[0]

        folio.add_charge(self.burger, qty=1.0)
        folio.add_charge(self.laundry, qty=2.0)
        self.assertEqual(folio.amount_total, 35.0)

        # Create Guest Invoice
        action = folio.action_create_invoice()
        invoice = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(invoice.partner_id, self.guest)
        self.assertEqual(len(invoice.invoice_line_ids), 2)
        self.assertEqual(invoice.amount_untaxed, 35.0)

        # All lines should now be marked as posted
        self.assertTrue(all(line.is_posted for line in folio.line_ids))

        # Trying to invoice again should raise error since there are no uninvoiced lines
        with self.assertRaises(UserError):
            folio.action_create_invoice()
