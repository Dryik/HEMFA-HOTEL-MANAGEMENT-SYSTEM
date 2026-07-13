from odoo import http
from odoo.http import content_disposition, request


class HotelReportDownload(http.Controller):
    @http.route("/hotel/reports/xlsx/<int:wizard_id>", type="http", auth="user")
    def download_xlsx(self, wizard_id, **kwargs):
        wizard = request.env["hotel.report.wizard"].browse(wizard_id).exists()
        if not wizard:
            return request.not_found()
        wizard.check_access("read")
        filename = f"{wizard.report_type}-{wizard.date}.xlsx"
        return request.make_response(
            wizard._build_xlsx(),
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
