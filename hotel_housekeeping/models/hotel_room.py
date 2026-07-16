from odoo import models


class HotelRoom(models.Model):
    _inherit = "hotel.room"

    def write(self, vals):
        res = super().write(vals)
        if "hk_status" in vals and vals["hk_status"] == "dirty":
            self._create_housekeeping_task()
        return res

    def _create_housekeeping_task(self):
        task_model = self.env["hotel.housekeeping.task"].sudo()
        reservation_model = self.env["hotel.reservation"].sudo()
        for room in self:
            existing = task_model.search_count(
                [
                    ("room_id", "=", room.id),
                    ("state", "not in", ("cleaned", "cancel")),
                ]
            )
            if not existing:
                reservation = reservation_model.search(
                    [
                        ("room_id", "=", room.id),
                        ("state", "=", "checked_out"),
                    ],
                    order="actual_checkout desc, id desc",
                    limit=1,
                )
                task_model.create(
                    {
                        "room_id": room.id,
                        "priority": "2" if room.occupancy_state == "checkout" else "1",
                        "reservation_id": reservation.id,
                        "trigger_type": "post_checkout" if reservation else "manual",
                        "source_key": f"post_checkout:{reservation.id}" if reservation else False,
                    }
                )
        return True
