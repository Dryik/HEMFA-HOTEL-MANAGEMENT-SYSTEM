from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Housekeeping status lives on the room so the board and the
# discrepancy report read one field; hotel_housekeeping drives it.
HK_STATUS = [
    ("clean", "Clean"),
    ("dirty", "Dirty"),
    ("inspected", "Inspected"),
]

# Front-office occupancy state. Stored selection for now; becomes a
# computed field driven by reservations in hotel_reservation.
OCCUPANCY_STATE = [
    ("vacant", "Vacant"),
    ("reserved", "Reserved"),
    ("occupied", "Occupied"),
    ("checkout", "Checked Out"),
]


class HotelRoom(models.Model):
    _name = "hotel.room"
    _description = "Hotel Room"
    _inherit = ["mail.thread"]
    _order = "property_id, floor_id, name"

    name = fields.Char(string="Room Number", required=True, tracking=True)
    active = fields.Boolean(default=True)
    floor_id = fields.Many2one(
        "hotel.floor", required=True, ondelete="restrict", index=True
    )
    property_id = fields.Many2one(
        related="floor_id.property_id", store=True, index=True
    )
    room_type_id = fields.Many2one(
        "hotel.room.type", required=True, ondelete="restrict", tracking=True
    )
    amenity_ids = fields.Many2many(
        "hotel.amenity",
        string="Extra Amenities",
        help="Amenities beyond the room type's standard set.",
    )
    telephone_extension = fields.Char()
    notes = fields.Text()

    occupancy_state = fields.Selection(
        OCCUPANCY_STATE, default="vacant", tracking=True, index=True
    )
    hk_status = fields.Selection(
        HK_STATUS,
        string="Housekeeping Status",
        default="clean",
        tracking=True,
        index=True,
    )
    out_of_order = fields.Boolean(
        tracking=True,
        help="Set by an open room-impacting maintenance request. Removes "
        "the room from sellable inventory.",
    )
    admin_use = fields.Boolean(
        string="House Use",
        tracking=True,
        help="Room reserved for hotel / staff use; excluded from "
        "sellable inventory and occupancy percentages.",
    )
    is_sellable = fields.Boolean(
        compute="_compute_is_sellable",
        store=True,
        help="Counts toward availability and the occupancy denominator.",
    )

    _name_property_uniq = models.Constraint(
        "unique (name, property_id)",
        "Room number must be unique per property.",
    )

    @api.depends("active", "out_of_order", "admin_use")
    def _compute_is_sellable(self):
        for room in self:
            room.is_sellable = (
                room.active and not room.out_of_order and not room.admin_use
            )

    @api.depends("name", "floor_id.property_id.code")
    def _compute_display_name(self):
        for room in self:
            code = room.property_id.code
            room.display_name = f"[{code}] {room.name}" if code else room.name

    def unlink(self):
        for room in self:
            active_res = self.env["hotel.reservation"].search_count(
                [
                    ("room_id", "=", room.id),
                    ("state", "in", ("confirmed", "checked_in")),
                ]
            )
            if active_res:
                raise UserError(_("You cannot delete room %s because it has active reservations.") % room.name)
        return super().unlink()

