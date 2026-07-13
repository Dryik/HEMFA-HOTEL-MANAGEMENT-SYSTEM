from odoo import api, models


def _report_values(env, docids):
    wizards = env["hotel.report.wizard"].browse(docids)
    return {
        "doc_ids": docids,
        "doc_model": "hotel.report.wizard",
        "docs": wizards,
        "payloads": {wizard.id: wizard._get_report_payload() for wizard in wizards},
    }


class ReportDailyMovement(models.AbstractModel):
    _name = "report.hotel_reports.report_daily_movement"
    _description = "Daily Movement Report Renderer"

    @api.model
    def _get_report_values(self, docids, data=None):
        return _report_values(self.env, docids)


class ReportLandscapeDetail(models.AbstractModel):
    _name = "report.hotel_reports.report_landscape_detail"
    _description = "Hotel Landscape Detail Report Renderer"

    @api.model
    def _get_report_values(self, docids, data=None):
        return _report_values(self.env, docids)


class ReportFinancialSummary(models.AbstractModel):
    _name = "report.hotel_reports.report_financial_summary"
    _description = "Hotel Financial Summary Report Renderer"

    @api.model
    def _get_report_values(self, docids, data=None):
        return _report_values(self.env, docids)
