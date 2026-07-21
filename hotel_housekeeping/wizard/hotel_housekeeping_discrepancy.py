from odoo import api, fields, models

class HotelHousekeepingDiscrepancyWizard(models.TransientModel):
    _name = "hotel.housekeeping.discrepancy.wizard"
    _description = "Housekeeping Discrepancy Reconciliation Wizard"

    property_id = fields.Many2one(
        "hotel.property",
        string="Property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    line_ids = fields.One2many(
        "hotel.housekeeping.discrepancy.wizard.line",
        "wizard_id",
        string="Discrepancy Lines",
    )

    @api.onchange("property_id")
    def _onchange_property_id(self):
        if not self.property_id:
            return
        
        rooms = self.env["hotel.room"].search([("property_id", "=", self.property_id.id)])
        lines = []
        for room in rooms:
            default_hk = "occupied" if room.occupancy_state == "occupied" else "vacant"
            lines.append((0, 0, {
                "room_id": room.id,
                "fo_occupancy": room.occupancy_state,
                "hk_occupancy": default_hk,
                "hk_status": room.hk_status,
            }))
        self.line_ids = [(5, 0, 0)] + lines

    def action_apply(self):
        for line in self.line_ids:
            if line.room_id.hk_status != line.hk_status:
                line.room_id._set_housekeeping_status(line.hk_status)
        return {"type": "ir.actions.act_window_close"}

class HotelHousekeepingDiscrepancyWizardLine(models.TransientModel):
    _name = "hotel.housekeeping.discrepancy.wizard.line"
    _description = "Housekeeping Discrepancy Reconciliation Line"

    wizard_id = fields.Many2one(
        "hotel.housekeeping.discrepancy.wizard",
        string="Wizard",
        ondelete="cascade",
    )
    room_id = fields.Many2one(
        "hotel.room",
        string="Room",
        required=True,
        readonly=True,
    )
    fo_occupancy = fields.Selection(
        [
            ("vacant", "Vacant"),
            ("reserved", "Reserved"),
            ("occupied", "Occupied"),
            ("checkout", "Checked Out"),
        ],
        string="FO Status",
        readonly=True,
    )
    hk_occupancy = fields.Selection(
        [
            ("vacant", "Vacant"),
            ("occupied", "Occupied"),
        ],
        string="Housekeeping Physical Occupancy",
        required=True,
    )
    hk_status = fields.Selection(
        [
            ("clean", "Clean"),
            ("dirty", "Dirty"),
            ("inspected", "Inspected"),
        ],
        string="Cleaning Status",
        required=True,
    )
    is_discrepancy = fields.Boolean(
        string="Discrepancy?",
        compute="_compute_is_discrepancy",
        store=True,
    )

    @api.depends("fo_occupancy", "hk_occupancy")
    def _compute_is_discrepancy(self):
        for line in self:
            fo_occ = line.fo_occupancy
            hk_occ = line.hk_occupancy
            if fo_occ == "occupied" and hk_occ != "occupied":
                line.is_discrepancy = True
            elif fo_occ != "occupied" and hk_occ == "occupied":
                line.is_discrepancy = True
            else:
                line.is_discrepancy = False
