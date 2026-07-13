from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestHotelHousekeeping(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create({
            "name": "Housekeeping Test Hotel",
        })
        cls.floor = cls.env["hotel.floor"].create({
            "name": "Floor 1",
            "property_id": cls.property.id,
        })
        cls.room_type = cls.env["hotel.room.type"].create({
            "name": "Deluxe Room",
            "code": "DLX",
        })
        cls.room = cls.env["hotel.room"].create({
            "name": "Room 101",
            "property_id": cls.property.id,
            "floor_id": cls.floor.id,
            "room_type_id": cls.room_type.id,
            "hk_status": "clean",
        })
        cls.cleaner = cls.env["res.users"].create({
            "name": "Cleaner Bob",
            "login": "cleaner_bob",
            "email": "bob@example.com",
            "group_ids": [(6, 0, [cls.env.ref("hotel_base.group_hotel_housekeeping").id])],
            "hotel_property_ids": [(6, 0, [cls.property.id])],
            "default_hotel_property_id": cls.property.id,
        })

    def test_task_lifecycle(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        self.assertEqual(task.state, "new")

        task.action_start()
        self.assertEqual(task.state, "cleaning")
        self.assertTrue(task.date_start)
        self.assertEqual(task.cleaner_id, self.env.user)

        task.action_complete()
        self.assertEqual(task.state, "cleaned")
        self.assertTrue(task.date_completed)
        self.assertEqual(self.room.hk_status, "clean")

    def test_room_dirty_auto_trigger(self):
        self.room.write({"hk_status": "dirty"})
        task = self.env["hotel.housekeeping.task"].search([("room_id", "=", self.room.id)])
        self.assertEqual(len(task), 1)
        self.assertEqual(task.state, "new")

        self.room.write({"hk_status": "dirty"})
        task_count = self.env["hotel.housekeeping.task"].search_count([("room_id", "=", self.room.id)])
        self.assertEqual(task_count, 1)

    def test_discrepancy_wizard(self):
        room2 = self.env["hotel.room"].create({
            "name": "Room 102",
            "property_id": self.property.id,
            "floor_id": self.floor.id,
            "room_type_id": self.room_type.id,
            "hk_status": "dirty",
            "occupancy_state": "occupied",
        })

        wizard = self.env["hotel.housekeeping.discrepancy.wizard"].create({
            "property_id": self.property.id,
        })
        wizard._onchange_property_id()

        self.assertEqual(len(wizard.line_ids), 2)

        line_room1 = wizard.line_ids.filtered(lambda l: l.room_id == self.room)
        line_room2 = wizard.line_ids.filtered(lambda l: l.room_id == room2)

        self.assertEqual(line_room1.fo_occupancy, "vacant")
        self.assertEqual(line_room1.hk_occupancy, "vacant")
        self.assertFalse(line_room1.is_discrepancy)

        self.assertEqual(line_room2.fo_occupancy, "occupied")
        self.assertEqual(line_room2.hk_occupancy, "occupied")
        self.assertFalse(line_room2.is_discrepancy)

        line_room2.write({"hk_occupancy": "vacant"})
        self.assertTrue(line_room2.is_discrepancy)

        line_room1.write({"hk_status": "inspected"})
        wizard.action_apply()

        self.assertEqual(self.room.hk_status, "inspected")

    def test_task_unlink_restrictions(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        task.unlink()

        task2 = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        task2.action_start()
        with self.assertRaises(UserError):
            task2.unlink()

        task2.action_cancel()
        task2.unlink()

    def test_cannot_complete_from_new(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        with self.assertRaises(UserError):
            task.action_complete()

    def test_cannot_start_when_cleaning(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        task.action_start()
        with self.assertRaises(UserError):
            task.action_start()

    def test_cancel_blocked_when_cleaned(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        task.action_start()
        task.action_complete()
        with self.assertRaises(UserError):
            task.action_cancel()

    def test_completed_task_is_immutable(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        task.action_start()
        task.action_complete()
        with self.assertRaises(UserError):
            task.write({"notes": "Changed after completion"})

    def test_state_cannot_bypass_actions(self):
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        with self.assertRaises(UserError):
            task.write({"state": "cleaned"})
        with self.assertRaises(UserError):
            task.with_context(hotel_housekeeping_transition=True).write(
                {"state": "cleaned"}
            )

    def test_tasks_are_property_scoped(self):
        other_property = self.env["hotel.property"].create(
            {"name": "Other Housekeeping Hotel", "code": "OHH"}
        )
        other_floor = self.env["hotel.floor"].create(
            {"name": "Other Floor", "property_id": other_property.id}
        )
        other_room = self.env["hotel.room"].create(
            {
                "name": "OH101",
                "floor_id": other_floor.id,
                "room_type_id": self.room_type.id,
            }
        )
        hidden_task = self.env["hotel.housekeeping.task"].create(
            {"room_id": other_room.id}
        )
        visible = self.env["hotel.housekeeping.task"].with_user(
            self.cleaner
        ).search([])
        self.assertNotIn(hidden_task, visible)
