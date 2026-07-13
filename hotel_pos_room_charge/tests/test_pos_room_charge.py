from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPosRoomCharge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.property = cls.env["hotel.property"].create(
            {"name": "POS Test Hotel", "code": "PTH"}
        )
        cls.floor = cls.env["hotel.floor"].create(
            {"name": "Floor P1", "property_id": cls.property.id}
        )
        cls.room_type = cls.env["hotel.room.type"].create(
            {"name": "POS Suite", "base_price": 200.0}
        )
        cls.room = cls.env["hotel.room"].create(
            {
                "name": "P101",
                "floor_id": cls.floor.id,
                "room_type_id": cls.room_type.id,
            }
        )
        cls.guest = cls.env["res.partner"].create(
            {"name": "POS Guest", "is_hotel_guest": True}
        )

        cls.restaurant_categ = cls.env["product.category"].create(
            {"name": "POS Restaurant"}
        )
        cls.meal = cls.env["product.product"].create(
            {
                "name": "Grilled Fish",
                "type": "consu",
                "list_price": 25.0,
                "categ_id": cls.restaurant_categ.id,
                "available_in_pos": True,
                "taxes_id": [(6, 0, [])],
            }
        )

        cls.clearing_account = cls.env["account.account"].create(
            {
                "name": "POS Room Charge Clearing Test",
                "code": "TSTPCC",
                "account_type": "asset_receivable",
                "reconcile": True,
            }
        )
        cls.transfer_journal = cls.env["account.journal"].create(
            {
                "name": "POS Room Charge Transfer Test",
                "type": "general",
                "code": "PRCT",
            }
        )
        cls.property.write(
            {
                "room_charge_clearing_account_id": cls.clearing_account.id,
                "room_charge_journal_id": cls.transfer_journal.id,
            }
        )

        cls.room_charge_method = cls.env["pos.payment.method"].create(
            {
                "name": "Room Charge",
                "is_room_charge": True,
                "hotel_property_id": cls.property.id,
                "receivable_account_id": cls.clearing_account.id,
            }
        )
        # Register every method before open_ui(): payment methods
        # cannot be modified on a config while a session is open.
        cls.cash_method = cls.env["pos.payment.method"].create(
            {"name": "Test Cash", "is_room_charge": False}
        )
        cls.pos_config = cls.env["pos.config"].create(
            {
                "name": "Hotel Restaurant POS",
                "payment_method_ids": [
                    (4, cls.room_charge_method.id),
                    (4, cls.cash_method.id),
                ],
                "hotel_property_id": cls.property.id,
            }
        )
        cls.pos_config.open_ui()
        cls.session = cls.pos_config.current_session_id

        cls.other_property = cls.env["hotel.property"].create(
            {"name": "Other POS Test Hotel", "code": "OPH"}
        )
        cls.other_pos_config = cls.env["pos.config"].create(
            {
                "name": "Other Hotel Restaurant POS",
                "hotel_property_id": cls.other_property.id,
                "payment_method_ids": [(6, 0, [cls.cash_method.id])],
            }
        )
        cls.other_room_charge_method = cls.env["pos.payment.method"].create(
            {
                "name": "Other Room Charge",
                "is_room_charge": False,
                "hotel_property_id": cls.other_property.id,
            }
        )
        cls.fb_user = cls.env["res.users"].create(
            {
                "name": "Property F&B User",
                "login": "property_fb_pos_test",
                "group_ids": [(4, cls.env.ref("hotel_base.group_hotel_fb").id)],
                "hotel_property_ids": [(6, 0, [cls.property.id])],
                "default_hotel_property_id": cls.property.id,
            }
        )

        cls.checkin = fields.Datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def _checked_in_reservation(self):
        reservation = self.env["hotel.reservation"].create(
            {
                "partner_id": self.guest.id,
                "property_id": self.property.id,
                "room_id": self.room.id,
                "room_type_id": self.room_type.id,
                "checkin_date": self.checkin,
                "checkout_date": self.checkin + timedelta(days=2),
            }
        )
        reservation.action_confirm()
        reservation.action_check_in()
        return reservation

    def _pos_order(self, partner=None, qty=1.0):
        amount = self.meal.list_price * qty
        order = self.env["pos.order"].create(
            {
                "session_id": self.session.id,
                "partner_id": partner.id if partner else False,
                "amount_tax": 0.0,
                "amount_total": amount,
                "amount_paid": amount,
                "amount_return": 0.0,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.meal.id,
                            "qty": qty,
                            "price_unit": self.meal.list_price,
                            "price_subtotal": amount,
                            "price_subtotal_incl": amount,
                        },
                    )
                ],
            }
        )
        self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "payment_method_id": self.room_charge_method.id,
                "amount": amount,
            }
        )
        return order

    def test_fb_pos_records_are_property_scoped(self):
        configs = self.env["pos.config"].with_user(self.fb_user).search([])
        self.assertIn(self.pos_config, configs)
        self.assertNotIn(self.other_pos_config, configs)

        methods = self.env["pos.payment.method"].with_user(self.fb_user).search([])
        self.assertIn(self.room_charge_method, methods)
        self.assertIn(self.cash_method, methods)
        self.assertNotIn(self.other_room_charge_method, methods)

    def test_pos_config_view_uses_stable_title_anchor(self):
        parent_arch = self.env.ref("point_of_sale.pos_config_view_form").arch_db
        inherited_arch = self.env.ref(
            "hotel_pos_room_charge.pos_config_view_form_hotel_property"
        ).arch_db
        self.assertIn('id="title"', parent_arch)
        self.assertIn("//div[@id='title']", inherited_arch)

    def test_room_charge_posts_to_folio(self):
        reservation = self._checked_in_reservation()
        folio = reservation.folio_ids[0]
        order = self._pos_order(partner=self.guest)

        order.action_pos_order_paid()

        charged = folio.line_ids.filtered(lambda l: l.pos_order_id == order)
        self.assertEqual(len(charged), 1)
        self.assertEqual(charged.amount, 25.0)
        self.assertEqual(charged.payee_partner_id, self.guest)
        self.assertFalse(charged.invoiceable)
        self.assertEqual(charged.lock_state, "pos")
        self.assertEqual(charged.accounting_move_id.state, "posted")
        self.assertEqual(order.hotel_room_charge_move_id, charged.accounting_move_id)
        with self.assertRaises(UserError):
            charged.write({"pos_order_id": False, "pos_order_line_id": False})

    def test_room_charge_is_idempotent(self):
        reservation = self._checked_in_reservation()
        folio = reservation.folio_ids[0]
        order = self._pos_order(partner=self.guest)
        order.action_pos_order_paid()
        # A second posting attempt must not duplicate folio lines.
        order._post_room_charges()
        charged = folio.line_ids.filtered(lambda l: l.pos_order_id == order)
        self.assertEqual(len(charged), 1)

    def test_split_payment_rejected(self):
        self._checked_in_reservation()
        order = self._pos_order(partner=self.guest)
        # Replace half the room-charge amount with a cash payment.
        room_payment = order.payment_ids[0]
        room_payment.amount = 12.5
        self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "payment_method_id": self.cash_method.id,
                "amount": 12.5,
            }
        )
        with self.assertRaises(UserError):
            order.action_pos_order_paid()

    def test_room_charge_requires_customer(self):
        self._checked_in_reservation()
        order = self._pos_order(partner=None)
        with self.assertRaises(UserError):
            order.action_pos_order_paid()

    def test_room_charge_rejects_checked_out_guest(self):
        reservation = self._checked_in_reservation()
        reservation.checkout_balance_override_reason = "POS checkout test"
        reservation.action_check_out()
        order = self._pos_order(partner=self.guest)
        with self.assertRaises(UserError):
            order.action_pos_order_paid()

    def test_room_charge_respects_service_block(self):
        reservation = self._checked_in_reservation()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.restaurant_categ.id,
                "restriction_type": "blocked",
            }
        )
        order = self._pos_order(partner=self.guest)
        with self.assertRaises(UserError):
            order.action_pos_order_paid()

    def test_room_charge_respects_daily_limit(self):
        reservation = self._checked_in_reservation()
        self.env["hotel.service.restriction"].create(
            {
                "reservation_id": reservation.id,
                "category_id": self.restaurant_categ.id,
                "restriction_type": "limited",
                "daily_limit": 30.0,
            }
        )
        # First meal (25.0) fits under the 30.0 daily limit.
        order1 = self._pos_order(partner=self.guest)
        order1.action_pos_order_paid()
        # Second meal would exceed it.
        order2 = self._pos_order(partner=self.guest)
        with self.assertRaises(UserError):
            order2.action_pos_order_paid()
