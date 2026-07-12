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
            }
        )

        cls.room_charge_method = cls.env["pos.payment.method"].create(
            {"name": "Room Charge", "is_room_charge": True}
        )
        cls.pos_config = cls.env["pos.config"].create(
            {
                "name": "Hotel Restaurant POS",
                "payment_method_ids": [(4, cls.room_charge_method.id)],
            }
        )
        cls.pos_config.open_ui()
        cls.session = cls.pos_config.current_session_id

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

    def test_room_charge_posts_to_folio(self):
        reservation = self._checked_in_reservation()
        folio = reservation.folio_ids[0]
        order = self._pos_order(partner=self.guest)

        order.action_pos_order_paid()

        charged = folio.line_ids.filtered(lambda l: l.pos_order_id == order)
        self.assertEqual(len(charged), 1)
        self.assertEqual(charged.amount, 25.0)
        self.assertEqual(charged.payee_partner_id, self.guest)

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
        cash_method = self.env["pos.payment.method"].create(
            {"name": "Test Cash", "is_room_charge": False}
        )
        # pos.payment validates its method against the session config.
        self.pos_config.write({"payment_method_ids": [(4, cash_method.id)]})
        order = self._pos_order(partner=self.guest)
        # Replace half the room-charge amount with a cash payment.
        room_payment = order.payment_ids[0]
        room_payment.amount = 12.5
        self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "payment_method_id": cash_method.id,
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
