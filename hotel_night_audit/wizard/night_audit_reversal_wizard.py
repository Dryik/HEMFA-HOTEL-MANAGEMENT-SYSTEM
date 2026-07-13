from odoo import fields, models


class HotelNightAuditReversalWizard(models.TransientModel):
    _name = "hotel.night.audit.reversal.wizard"
    _description = "Night Audit Reversal Reason"

    audit_id = fields.Many2one("hotel.night.audit", required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_reverse(self):
        self.ensure_one()
        self.audit_id.action_reverse(self.reason)
        return {"type": "ir.actions.act_window_close"}
