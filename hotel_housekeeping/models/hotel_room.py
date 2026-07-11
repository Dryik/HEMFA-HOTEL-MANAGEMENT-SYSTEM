from odoo import api, fields, models

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
                    ("state", "not in", ("inspected", "cancel")),
                ]
            )
            if not existing:
                self.env["hotel.housekeeping.task"].create(
                    {
                        "room_id": room.id,
                        "state": "draft",
                        "priority": "2" if room.occupancy_state == "checkout" else "1",
                    }
                )
        return True
