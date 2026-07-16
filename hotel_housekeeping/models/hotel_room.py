from odoo import models

class HotelRoom(models.Model):
    _inherit = "hotel.room"

    def write(self, vals):
        res = super().write(vals)
        if "hk_status" in vals and vals["hk_status"] == "dirty":
            self._create_housekeeping_task()
        return res

    def _create_housekeeping_task(self):
        for room in self:
            existing = self.env["hotel.housekeeping.task"].search_count(
                [
                    ("room_id", "=", room.id),
                    ("state", "not in", ("cleaned", "cancel")),
                ]
            )
            if not existing:
                reservation = self.env["hotel.reservation"].search(
                    [
                        ("room_id", "=", room.id),
                        ("state", "=", "checked_out"),
                    ],
                    order="actual_checkout desc, id desc",
                    limit=1,
                )
                self.env["hotel.housekeeping.task"].create(
                    {
                        "room_id": room.id,
                        "priority": "2" if room.occupancy_state == "checkout" else "1",
                        "reservation_id": reservation.id,
                        "trigger_type": "post_checkout" if reservation else "manual",
                        "source_key": f"post_checkout:{reservation.id}" if reservation else False,
                    }
                )
        return True
