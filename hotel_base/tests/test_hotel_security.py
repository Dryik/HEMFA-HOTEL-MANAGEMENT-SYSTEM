from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelCompanySecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property_a = cls.env["hotel.property"]._get_default_property()
        cls.company_b = cls.env["res.company"].create({"name": "Other Hotel Company"})
        cls.property_b = cls.env["hotel.property"].create(
            {
                "name": "Other Hotel",
                "code": "OTH",
                "company_id": cls.company_b.id,
            }
        )
        cls.floor_a = cls.env["hotel.floor"].create(
            {"name": "A", "property_id": cls.property_a.id}
        )
        cls.floor_b = cls.env["hotel.floor"].create(
            {"name": "B", "property_id": cls.property_b.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Security Room Type", "property_id": cls.property_a.id}
        )
        cls.room_type_b = cls.env["hotel.room.type"].create(
            {
                "name": "Other Company Room Type",
                "property_id": cls.property_b.id,
            }
        )
        cls.room_a = cls.env["hotel.room"].create(
            {
                "name": "SEC-101",
                "floor_id": cls.floor_a.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.room_b = cls.env["hotel.room"].create(
            {
                "name": "201",
                "floor_id": cls.floor_b.id,
                "room_type_id": cls.room_type_b.id,
            }
        )
        cls.frontdesk = cls.env["res.users"].create(
            {
                "name": "Property Front Desk",
                "login": "property_frontdesk_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_frontdesk").id)
                ],
            }
        )
        cls.housekeeper = cls.env["res.users"].create(
            {
                "name": "Property Housekeeper",
                "login": "property_housekeeper_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_housekeeping").id)
                ],
            }
        )
        cls.contact_editor = cls.env["res.users"].create(
            {
                "name": "Restricted Contact Editor",
                "login": "restricted_contact_editor_test",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("base.group_partner_manager").id)
                ],
            }
        )
        cls.accountant = cls.env["res.users"].create(
            {
                "name": "Property Accountant",
                "login": "property_accountant_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_accountant").id)
                ],
            }
        )
        cls.system_admin = cls.env["res.users"].create(
            {
                "name": "Hotel Technical Administrator",
                "login": "hotel_technical_admin_test",
                "group_ids": [(4, cls.env.ref("base.group_system").id)],
                "company_id": cls.env.company.id,
                "company_ids": [
                    (6, 0, [cls.env.company.id, cls.company_b.id])
                ],
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {
                "name": "Protected Guest",
                "is_hotel_guest": True,
                "guest_id_number": "P-SECRET",
                "company_id": cls.env.company.id,
            }
        )
        cls.other_guest = cls.env["res.partner"].create(
            {
                "name": "Other Property Guest",
                "is_hotel_guest": True,
                "company_id": cls.company_b.id,
            }
        )

    def test_company_rules_and_default(self):
        rooms = self.env["hotel.room"].with_user(self.frontdesk).search([])
        self.assertIn(self.room_a, rooms)
        self.assertNotIn(self.room_b, rooms)
        partners = self.env["res.partner"].with_user(self.frontdesk).search(
            [("is_hotel_guest", "=", True)]
        )
        self.assertIn(self.guest, partners)
        self.assertNotIn(self.other_guest, partners)
        accounting_partners = self.env["res.partner"].with_user(
            self.accountant
        ).search([("is_hotel_guest", "=", True)])
        self.assertIn(self.guest, accounting_partners)
        self.assertNotIn(self.other_guest, accounting_partners)
        default = self.env["hotel.property"].with_user(
            self.frontdesk
        )._get_default_property()
        self.assertEqual(default, self.property_a)
        matching_companies = self.env["res.company"].search(
            [("hotel_property_config_id", "=", self.property_a.id)]
        )
        self.assertIn(self.env.company, matching_companies)
        self.assertNotIn(self.company_b, matching_companies)

    def test_user_context_seeds_default_frontdesk_workspace(self):
        context = self.env["res.users"].with_user(self.frontdesk).context_get()
        self.assertEqual(context["hotel_property_id"], self.property_a.id)
        self.assertEqual(
            context["hotel_business_date"],
            fields.Date.to_string(
                self.property_a.get_business_date()
            ),
        )
        public_context = (
            self.env["res.users"]
            .with_user(self.env.ref("base.public_user"))
            .context_get()
        )
        self.assertNotIn("hotel_property_id", public_context)

    def test_system_administrator_can_use_all_allowed_companies(self):
        self.assertTrue(
            self.system_admin.has_group("hotel_base.group_hotel_manager")
        )
        properties = (
            self.env["hotel.property"]
            .with_user(self.system_admin)
            .with_context(
                allowed_company_ids=[self.env.company.id, self.company_b.id]
            )
            .search([])
        )
        self.assertIn(self.property_a, properties)
        self.assertIn(self.property_b, properties)
        default_property = self.env["hotel.property"].with_user(
            self.system_admin
        )._get_default_property()
        self.assertIn(default_property, properties)

    def test_identity_fields_are_field_group_protected(self):
        values = self.guest.with_user(self.frontdesk).read(["guest_id_number"])
        self.assertEqual(values[0]["guest_id_number"], "P-SECRET")
        with self.assertRaises(AccessError):
            self.guest.with_user(self.housekeeper).read(["guest_id_number"])
        self.guest.with_user(self.accountant).read(["is_hotel_guest"])
        with self.assertRaises(AccessError):
            self.guest.with_user(self.accountant).read(["guest_id_number"])

    def test_parent_agency_default_is_safe_for_restricted_user(self):
        agency = self.env["res.partner"].create(
            {"name": "Restricted User Agency", "is_hotel_agency": True}
        )
        guest = self.env["res.partner"].create(
            {"name": "Restricted User Guest", "is_hotel_guest": True}
        )
        with self.assertRaises(AccessError):
            guest.with_user(self.contact_editor).read(["hotel_agency_id"])
        guest.with_user(self.contact_editor).write({"parent_id": agency.id})
        self.assertEqual(guest.sudo().hotel_agency_id, agency)

    def test_housekeeping_cannot_mutate_front_office_room_state(self):
        room = self.room_a.with_user(self.housekeeper)
        room.write({"hk_status": "dirty"})
        with self.assertRaises(UserError):
            room.write({"occupancy_state": "occupied"})
        with self.assertRaises(UserError):
            room.write({"out_of_order": True})
        with self.assertRaises(UserError):
            room.write({"name": "FORGED"})

    def test_noon_to_noon_business_day(self):
        start, end = self.property_a.get_business_day_bounds(date(2026, 7, 13))
        self.assertEqual(end - start, timedelta(days=1))
        self.assertEqual(
            self.property_a.get_business_date(start + timedelta(hours=1)),
            date(2026, 7, 13),
        )
        self.assertEqual(
            self.property_a.get_business_date(start - timedelta(hours=1)),
            date(2026, 7, 12),
        )

    def test_agency_commission_placeholder_is_property_scoped(self):
        agency = self.env["res.partner"].create(
            {"name": "Commission Agency", "is_hotel_agency": True}
        )
        configuration = self.env["hotel.agency.commission"].create(
            {
                "property_id": self.property_a.id,
                "agency_id": agency.id,
                "commission_type": "percent",
                "commission_rate": 7.5,
            }
        )
        visible = self.env["hotel.agency.commission"].with_user(
            self.frontdesk
        ).search([])
        self.assertIn(configuration, visible)
        with self.assertRaises(ValidationError):
            self.env["hotel.agency.commission"].create(
                {
                    "property_id": self.property_b.id,
                    "agency_id": agency.id,
                    "commission_type": "percent",
                    "commission_rate": 101.0,
                }
            )
