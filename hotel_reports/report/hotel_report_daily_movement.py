from odoo import api, models


class ReportDailyMovement(models.AbstractModel):
    _name = "report.hotel_reports.report_daily_movement"
    _description = "Daily Movement Report Renderer"

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env["hotel.report.wizard"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "hotel.report.wizard",
            "docs": wizards,
            "reservations_for": {
                wizard.id: wizard._get_reservations() for wizard in wizards
            },
            "payloads": {
                wizard.id: wizard._get_report_payload() for wizard in wizards
            },
        }
