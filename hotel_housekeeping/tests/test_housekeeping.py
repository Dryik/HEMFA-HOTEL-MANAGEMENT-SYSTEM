from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestHotelHousekeeping(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Setup Property
        cls.property = cls.env["hotel.property"].create({
            "name": "Housekeeping Test Hotel",
        })
        # Setup Floor
        cls.floor = cls.env["hotel.floor"].create({
            "name": "Floor 1",
            "property_id": cls.property.id,
        })
        # Setup Room Type
        cls.room_type = cls.env["hotel.room.type"].create({
            "name": "Deluxe Room",
            "code": "DLX",
        })
        # Setup Room
        cls.room = cls.env["hotel.room"].create({
            "name": "Room 101",
            "property_id": cls.property.id,
            "floor_id": cls.floor.id,
            "room_type_id": cls.room_type.id,
            "hk_status": "clean",
        })

        # Create Cleaner User
        cls.cleaner = cls.env["res.users"].create({
            "name": "Cleaner Bob",
            "login": "cleaner_bob",
            "email": "bob@example.com",
            "groups_id": [(6, 0, [cls.env.ref("hotel_base.group_hotel_housekeeping").id])],
        })

        # Create Supervisor User
        cls.supervisor = cls.env["res.users"].create({
            "name": "Supervisor Sally",
            "login": "supervisor_sally",
            "email": "sally@example.com",
            "groups_id": [(6, 0, [cls.env.ref("hotel_base.group_hotel_fo_supervisor").id])],
        })

    def test_housekeeping_task_lifecycle(self):
        # 1. Manually create a task
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        self.assertEqual(task.state, "draft")
        self.assertEqual(self.room.hk_status, "clean")

        # 2. Assign Cleaner
        task.write({"cleaner_id": self.cleaner.id})
        self.assertEqual(task.state, "assigned")
        self.assertTrue(task.date_assigned)

        # 3. Start Cleaning
        task.action_start()
        self.assertEqual(task.state, "cleaning")
        self.assertTrue(task.date_start)

        # 4. Complete Cleaning
        task.action_complete()
        self.assertEqual(task.state, "clean")
        self.assertTrue(task.date_completed)
        self.assertEqual(self.room.hk_status, "clean")  # updates room to clean

        # 5. Inspect Task
        task.with_user(self.supervisor).action_inspect()
        self.assertEqual(task.state, "inspected")
        self.assertEqual(task.inspector_id, self.supervisor)
        self.assertEqual(self.room.hk_status, "inspected")

    def test_room_dirty_auto_trigger(self):
        # 1. Update room hk_status to dirty
        self.room.write({"hk_status": "dirty"})

        # 2. Check if a task was auto-created in draft state
        task = self.env["hotel.housekeeping.task"].search([("room_id", "=", self.room.id)])
        self.assertEqual(len(task), 1)
        self.assertEqual(task.state, "draft")

        # 3. Re-setting to dirty again shouldn't create a second active task
        self.room.write({"hk_status": "dirty"})
        task_count = self.env["hotel.housekeeping.task"].search_count([("room_id", "=", self.room.id)])
        self.assertEqual(task_count, 1)

    def test_discrepancy_wizard(self):
        # 1. Create another room
        room2 = self.env["hotel.room"].create({
            "name": "Room 102",
            "property_id": self.property.id,
            "floor_id": self.floor.id,
            "room_type_id": self.room_type.id,
            "hk_status": "dirty",
            "occupancy_state": "occupied",
        })

        # 2. Launch Discrepancy Wizard
        wizard = self.env["hotel.housekeeping.discrepancy.wizard"].create({
            "property_id": self.property.id,
        })
        wizard._onchange_property_id()

        # 3. Verify populated lines
        self.assertEqual(len(wizard.line_ids), 2)
        
        line_room1 = wizard.line_ids.filtered(lambda l: l.room_id == self.room)
        line_room2 = wizard.line_ids.filtered(lambda l: l.room_id == room2)

        self.assertEqual(line_room1.fo_occupancy, "vacant")
        self.assertEqual(line_room1.hk_occupancy, "vacant")
        self.assertFalse(line_room1.is_discrepancy)

        self.assertEqual(line_room2.fo_occupancy, "occupied")
        self.assertEqual(line_room2.hk_occupancy, "occupied")
        self.assertFalse(line_room2.is_discrepancy)

        # 4. Modify physical occupancy to trigger discrepancy
        line_room2.write({"hk_occupancy": "vacant"})
        self.assertTrue(line_room2.is_discrepancy)

        # 5. Modify clean status on line 1 and apply
        line_room1.write({"hk_status": "inspected"})
        wizard.action_apply()

        # Verify that Room 101 status is updated to inspected
        self.assertEqual(self.room.hk_status, "inspected")

    def test_task_unlink_restrictions(self):
        # 1. Create task
        task = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        # Draft can be deleted
        task.unlink()

        # 2. Re-create and assign
        task2 = self.env["hotel.housekeeping.task"].create({
            "room_id": self.room.id,
        })
        task2.write({"cleaner_id": self.cleaner.id})
        self.assertEqual(task2.state, "assigned")

        # Trying to delete assigned task should fail
        with self.assertRaises(UserError):
            task2.unlink()

        # Cancelled task can be deleted
        task2.action_cancel()
        task2.unlink()
