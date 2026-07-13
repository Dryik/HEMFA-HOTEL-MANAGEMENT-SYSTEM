from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestHotelMaintenance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "Maintenance Test Hotel", "code": "MTH"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor M1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "Maintenance Suite", "base_price": 100.0}
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "M101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.technician = cls.env["res.users"].create(
            {
                "name": "Tech One",
                "login": "tech_one_maintenance_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_maintenance").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )
        # Odoo 19 has_group checks real membership even for the test
        # superuser, so verification needs an actual manager user.
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Hotel Manager",
                "login": "manager_maintenance_test",
                "group_ids": [
                    (4, cls.env.ref("hotel_base.group_hotel_manager").id)
                ],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )

    def _request(self, **overrides):
        vals = {
            "room_id": self.room.id,
            "description": "AC not cooling",
            "blocks_room": True,
        }
        vals.update(overrides)
        return self.env["hotel.maintenance.request"].create(vals)

    def test_full_lifecycle(self):
        req = self._request()
        self.assertTrue(req.name.startswith("MNT/"))
        self.assertEqual(req.state, "new")
        self.assertEqual(req.property_id, self.property)

        req.action_confirm()
        self.assertEqual(req.state, "confirmed")
        req.action_start()
        self.assertEqual(req.state, "in_progress")
        # Starting without an explicit technician assigns the current user.
        self.assertTrue(req.technician_id)
        req.action_done()
        self.assertEqual(req.state, "done")
        req.with_user(self.manager).action_verify()
        self.assertEqual(req.state, "verified")

    def test_blocking_request_takes_room_out_of_order(self):
        req = self._request()
        # Reporting alone does not block the room yet.
        self.assertFalse(self.room.out_of_order)
        self.assertTrue(self.room.is_sellable)

        req.action_confirm()
        self.assertTrue(self.room.out_of_order)
        self.assertFalse(self.room.is_sellable)

        req.action_start()
        req.action_done()
        self.assertTrue(self.room.out_of_order)

        req.with_user(self.manager).action_verify()
        self.assertFalse(self.room.out_of_order)
        self.assertTrue(self.room.is_sellable)

    def test_cancel_releases_room(self):
        req = self._request()
        req.action_confirm()
        self.assertTrue(self.room.out_of_order)
        req.action_cancel()
        self.assertFalse(self.room.out_of_order)

    def test_room_stays_blocked_with_second_open_request(self):
        first = self._request()
        second = self._request(description="Broken shower")
        first.action_confirm()
        second.action_confirm()
        self.assertTrue(self.room.out_of_order)

        first.action_start()
        first.action_done()
        first.with_user(self.manager).action_verify()
        # Second request is still open, room must remain blocked.
        self.assertTrue(self.room.out_of_order)

        second.action_cancel()
        self.assertFalse(self.room.out_of_order)

    def test_toggling_blocks_room_resyncs(self):
        req = self._request(blocks_room=False)
        req.action_confirm()
        self.assertFalse(self.room.out_of_order)
        # Flagging an already-confirmed request must block immediately.
        req.blocks_room = True
        self.assertTrue(self.room.out_of_order)
        req.blocks_room = False
        self.assertFalse(self.room.out_of_order)

    def test_room_change_releases_old_room(self):
        other_room = self.env["hotel.room"].create(
            {
                "name": "M102",
                "floor_id": self.floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        req = self._request()
        req.action_confirm()
        self.assertTrue(self.room.out_of_order)
        req.room_id = other_room
        self.assertFalse(self.room.out_of_order)
        self.assertTrue(other_room.out_of_order)

    def test_non_manager_cannot_verify(self):
        req = self._request()
        req.action_confirm()
        req.action_start()
        req.action_done()
        with self.assertRaises(UserError):
            req.with_user(self.technician).action_verify()

    def test_blocking_requires_room(self):
        with self.assertRaises(UserError):
            self._request(room_id=False, blocks_room=True)

    def test_state_guards(self):
        req = self._request()
        with self.assertRaises(UserError):
            req.action_start()  # must be confirmed first
        with self.assertRaises(UserError):
            # As manager, so the state guard (not the group check) fires.
            req.with_user(self.manager).action_verify()  # must be done first
        req.action_confirm()
        with self.assertRaises(UserError):
            req.action_confirm()  # already confirmed

    def test_delete_guard(self):
        req = self._request()
        req.action_confirm()
        with self.assertRaises(UserError):
            req.unlink()
        req.action_cancel()
        req.unlink()

    def test_verified_request_is_immutable(self):
        req = self._request()
        req.action_confirm()
        req.action_start()
        req.action_done()
        req.with_user(self.manager).action_verify()
        with self.assertRaises(UserError):
            req.with_user(self.manager).write({"resolution_notes": "Changed"})

    def test_state_cannot_bypass_actions(self):
        req = self._request()
        with self.assertRaises(UserError):
            req.write({"state": "verified"})
        with self.assertRaises(UserError):
            req.with_context(hotel_maintenance_transition=True).write(
                {"state": "verified"}
            )

    def test_requests_are_property_scoped(self):
        other_property = self.env["hotel.property"].create(
            {"name": "Other Maintenance Hotel", "code": "OMH"}
        )
        hidden_request = self.env["hotel.maintenance.request"].create(
            {
                "property_id": other_property.id,
                "location": "Lobby",
                "description": "Hidden request",
            }
        )
        visible = self.env["hotel.maintenance.request"].with_user(
            self.technician
        ).search([])
        self.assertNotIn(hidden_request, visible)
