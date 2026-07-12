from odoo import fields, models


class HotelRoom(models.Model):
    _inherit = "hotel.room"

    maintenance_request_ids = fields.One2many(
        "hotel.maintenance.request", "room_id", string="Maintenance Requests"
    )
    open_maintenance_count = fields.Integer(
        compute="_compute_open_maintenance_count"
    )

    def _compute_open_maintenance_count(self):
        grouped = self.env["hotel.maintenance.request"]._read_group(
            [
                ("room_id", "in", self.ids),
                ("state", "in", ("new", "confirmed", "in_progress", "done")),
            ],
            ["room_id"],
            ["__count"],
        )
        counts = {room.id: count for room, count in grouped}
        for room in self:
            room.open_maintenance_count = counts.get(room.id, 0)
