import io

import xlsxwriter

from odoo import _, api, fields, models
from odoo.exceptions import UserError


REPORT_TYPES = [
    ("arrivals", "Arrivals"),
    ("departures", "Departures"),
    ("inhouse", "In-House Guests"),
    ("security", "Security / Police List"),
    ("occupancy", "Occupancy"),
    ("debtors", "Debtors"),
    ("discrepancy", "Housekeeping Discrepancy"),
    ("agency_advances", "Agency Advances"),
    ("pos_room_charges", "POS Room Charges"),
    ("folio_statement", "Consolidated Folio Statement"),
]

REPORT_ACCESS_GROUPS = {
    "hotel_base.group_hotel_frontdesk": {
        "arrivals",
        "departures",
        "inhouse",
        "security",
        "occupancy",
        "folio_statement",
    },
    "hotel_base.group_hotel_housekeeping": {"discrepancy"},
    "hotel_base.group_hotel_accountant": {
        "occupancy",
        "debtors",
        "agency_advances",
        "pos_room_charges",
        "folio_statement",
    },
}

REPORT_FAMILIES = {
    "security": "landscape",
    "debtors": "landscape",
    "agency_advances": "landscape",
    "pos_room_charges": "landscape",
    "folio_statement": "landscape",
}

REPORT_ACTIONS = {
    "operations": "hotel_reports.action_report_daily_movement",
    "landscape": "hotel_reports.action_report_landscape_detail",
}

ARABIC = {
    "Arrivals": "الوصول",
    "Departures": "المغادرة",
    "In-House Guests": "النزلاء المقيمون",
    "Security / Police List": "قائمة الأمن / الشرطة",
    "Occupancy": "الإشغال",
    "Debtors": "المدينون",
    "Housekeeping Discrepancy": "فروقات التدبير الفندقي",
    "Agency Advances": "دفعات الجهات المقدمة",
    "POS Room Charges": "مبيعات نقاط البيع على الغرف",
    "Consolidated Folio Statement": "كشف الحساب الموحد",
    "Room": "الغرفة",
    "Guest": "النزيل",
    "Nationality": "الجنسية",
    "Reservation": "الحجز",
    "Arrival": "الوصول",
    "Departure": "المغادرة",
    "Nights": "الليالي",
    "Agency / Entity": "الجهة",
    "ID Type": "نوع الهوية",
    "ID Number": "رقم الهوية",
    "Birth Date": "تاريخ الميلاد",
    "Coming From": "قادماً من",
    "Heading To": "متجهاً إلى",
    "Folio": "الحساب",
    "Total": "الإجمالي",
    "Paid": "المدفوع",
    "Due": "المستحق",
    "Currency": "العملة",
    "Journal": "اليومية",
    "Transactions": "الحركات",
    "Counted": "المعدود",
    "Difference": "الفرق",
    "Date": "التاريخ",
    "Rooms": "الغرف",
    "Occupied": "المشغول",
    "ADR": "متوسط سعر الغرفة",
    "RevPAR": "إيراد الغرفة المتاحة",
    "Revenue": "الإيراد",
    "Tax": "الضريبة",
    "FO Status": "حالة الاستقبال",
    "Housekeeping": "التدبير الفندقي",
    "Payment": "الدفعة",
    "Available": "المتاح",
    "POS Receipt": "إيصال نقطة البيع",
    "Source": "المصدر",
    "Description": "البيان",
    "Untaxed": "قبل الضريبة",
    "Accounting": "القيد المحاسبي",
    "Invoiced / Transferred": "المفوتر / المحول",
    "Payment / Advance": "دفعة / مبلغ مقدم",
}


class HotelReportWizard(models.TransientModel):
    _name = "hotel.report.wizard"
    _description = "Hotel Report Wizard"

    @api.model
    def _allowed_report_type_keys(self):
        if self.env.user.has_group("hotel_base.group_hotel_manager"):
            return {key for key, _label in REPORT_TYPES}
        allowed = set()
        for group_xmlid, report_types in REPORT_ACCESS_GROUPS.items():
            if self.env.user.has_group(group_xmlid):
                allowed.update(report_types)
        return allowed

    @api.model
    def _selection_report_types(self):
        allowed = self._allowed_report_type_keys()
        return [(key, label) for key, label in REPORT_TYPES if key in allowed]

    @api.model
    def _default_report_type(self):
        selection = self._selection_report_types()
        return selection[0][0] if selection else False

    report_type = fields.Selection(
        selection=REPORT_TYPES,
        required=True,
        default=_default_report_type,
    )
    date = fields.Date(required=True, default=fields.Date.context_today)
    property_id = fields.Many2one(
        "hotel.property",
        required=True,
        default=lambda self: self.env["hotel.property"]._get_default_property(),
    )
    language = fields.Selection(
        [("en", "English"), ("ar", "العربية")], default="en", required=True
    )
    folio_id = fields.Many2one(
        "hotel.folio", domain="[('property_id', '=', property_id)]"
    )

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields, attributes)
        report_type = result.get("report_type") or {}
        if "selection" in report_type:
            allowed = self._allowed_report_type_keys()
            report_type["selection"] = [
                (key, label)
                for key, label in report_type["selection"]
                if key in allowed
            ]
        return result

    def _day_window(self):
        self.ensure_one()
        return self.property_id.get_business_day_bounds(self.date)

    def _get_reservations(self):
        self.ensure_one()
        day_start, day_end = self._day_window()
        base = [("property_id", "=", self.property_id.id)]
        if self.report_type == "arrivals":
            domain = base + [
                ("state", "in", ("confirmed", "checked_in")),
                ("checkin_date", ">=", day_start),
                ("checkin_date", "<", day_end),
            ]
            order = "checkin_date, room_id"
        elif self.report_type == "departures":
            domain = base + [
                ("state", "in", ("checked_in", "checked_out")),
                ("checkout_date", ">=", day_start),
                ("checkout_date", "<", day_end),
            ]
            order = "checkout_date, room_id"
        else:
            domain = base + [("state", "=", "checked_in")]
            order = "room_id"
        return self.env["hotel.reservation"].search(domain, order=order)

    def _label(self, english):
        return ARABIC.get(english, english) if self.language == "ar" else english

    def _report_family(self):
        self.ensure_one()
        return REPORT_FAMILIES.get(self.report_type, "operations")

    @staticmethod
    def _column_widths(columns):
        wide_columns = {"guest", "agency", "description", "accounting"}
        compact_columns = {
            "room",
            "nights",
            "rooms",
            "occupied",
            "occupancy",
            "adr",
            "revpar",
            "revenue",
            "tax",
            "untaxed",
            "total",
            "paid",
            "due",
            "available",
            "counted",
            "difference",
            "currency",
        }
        weights = {
            key: 1.5 if key in wide_columns else 0.72 if key in compact_columns else 1.0
            for key, _label in columns
        }
        total = sum(weights.values()) or 1.0
        return {
            key: round(weight * 100.0 / total, 2) for key, weight in weights.items()
        }

    def _currency_summary(self, rows, measures):
        summary = []
        currencies = sorted(
            {row.get("currency") for row in rows if row.get("currency")}
        )
        for currency in currencies:
            currency_rows = [row for row in rows if row.get("currency") == currency]
            for key, label in measures:
                summary.append(
                    (
                        f"{self._label(label)} ({currency})",
                        sum(row.get(key, 0.0) or 0.0 for row in currency_rows),
                    )
                )
        return summary

    def _check_report_access(self):
        self.ensure_one()
        if self.report_type not in self._allowed_report_type_keys():
            raise UserError(_("Your hotel role cannot access this report type."))

    @staticmethod
    def _western(value):
        text = "" if value is None or value is False else str(value)
        return text.translate(
            str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
        )

    def _operational_datetime(self, value):
        """Format a UTC timestamp in the active hotel's timezone."""
        if not value:
            return ""
        local_value = fields.Datetime.context_timestamp(
            self.with_context(tz=self.property_id.timezone),
            fields.Datetime.to_datetime(value),
        )
        return self._western(local_value.strftime("%d/%m/%Y %H:%M"))

    def _movement_payload(self):
        reservations = self._get_reservations()
        security = self.report_type == "security"
        columns = [("room", "Room"), ("guest", "Guest"), ("nationality", "Nationality")]
        if security:
            columns += [
                ("id_type", "ID Type"),
                ("id_number", "ID Number"),
                ("birthdate", "Birth Date"),
                ("coming_from", "Coming From"),
                ("heading_to", "Heading To"),
            ]
        else:
            columns += [
                ("reservation", "Reservation"),
                ("arrival", "Arrival"),
                ("departure", "Departure"),
                ("nights", "Nights"),
                ("agency", "Agency / Entity"),
            ]
        rows = []
        for reservation in reservations:
            row = {
                "room": reservation.room_id.name or "",
                "guest": reservation.partner_id.name or "",
                "nationality": reservation.guest_nationality_id.name or "",
            }
            if security:
                row.update(
                    {
                        "id_type": reservation.partner_id.guest_id_type or "",
                        "id_number": reservation.partner_id.guest_id_number or "",
                        "birthdate": self._western(
                            reservation.partner_id.guest_birthdate
                        ),
                        "coming_from": reservation.coming_from or "",
                        "heading_to": reservation.heading_to or "",
                    }
                )
            else:
                row.update(
                    {
                        "reservation": reservation.name,
                        "arrival": self._operational_datetime(reservation.checkin_date),
                        "departure": self._operational_datetime(
                            reservation.checkout_date
                        ),
                        "nights": reservation.nights,
                        "agency": reservation.agency_id.name or "",
                    }
                )
            rows.append(row)
        return columns, rows

    def _get_report_payload(self):
        self.ensure_one()
        self._check_report_access()
        columns, rows = [], []
        summary = []
        if self.report_type in ("arrivals", "departures", "inhouse", "security"):
            columns, rows = self._movement_payload()
        elif self.report_type == "occupancy":
            columns = [
                ("date", "Date"),
                ("rooms", "Rooms"),
                ("occupied", "Occupied"),
                ("occupancy", "Occupancy"),
                ("adr", "ADR"),
                ("revpar", "RevPAR"),
                ("currency", "Currency"),
            ]
            day_start, day_end = self._day_window()
            rooms = self.env["hotel.room"].search(
                [
                    ("property_id", "=", self.property_id.id),
                    ("active", "=", True),
                    ("out_of_order", "=", False),
                    ("admin_use", "=", False),
                ]
            )
            stays = self.env["hotel.reservation"].search(
                [
                    ("property_id", "=", self.property_id.id),
                    ("room_id", "in", rooms.ids),
                    ("state", "not in", ("draft", "cancelled", "no_show")),
                    ("checkin_date", "<", day_end),
                    ("checkout_date", ">", day_start),
                ]
            )
            occupied = len(set(stays.mapped("room_id").ids))
            room_count = len(rooms)
            revenue = sum(stays.mapped("rate_night"))
            adr = revenue / occupied if occupied else 0.0
            revpar = revenue / room_count if room_count else 0.0
            rows = [{
                "date": self._western(self.date),
                "rooms": room_count,
                "occupied": occupied,
                "occupancy": occupied * 100.0 / room_count if room_count else 0.0,
                "adr": adr,
                "revpar": revpar,
                "currency": self.property_id.company_id.currency_id.name,
            }]
            summary = [
                (self._label("Rooms"), room_count),
                (self._label("Occupied"), occupied),
            ]
        elif self.report_type == "debtors":
            columns = [
                ("folio", "Folio"),
                ("guest", "Guest"),
                ("agency", "Agency / Entity"),
                ("total", "Total"),
                ("paid", "Paid"),
                ("due", "Due"),
                ("currency", "Currency"),
            ]
            folios = self.env["hotel.folio"].search(
                [("property_id", "=", self.property_id.id), ("amount_due", "!=", 0.0)]
            )
            rows = [
                {
                    "folio": folio.name,
                    "guest": folio.partner_id.name,
                    "agency": folio.agency_id.name or "",
                    "total": folio.amount_total,
                    "paid": folio.amount_paid,
                    "due": folio.amount_due,
                    "currency": folio.currency_id.name,
                }
                for folio in folios
            ]
            summary = self._currency_summary(
                rows, (("total", "Total"), ("paid", "Paid"), ("due", "Due"))
            )
        elif self.report_type == "discrepancy":
            columns = [
                ("room", "Room"),
                ("fo_status", "FO Status"),
                ("housekeeping", "Housekeeping"),
            ]
            rooms = self.env["hotel.room"].search(
                [("property_id", "=", self.property_id.id)]
            )
            rows = [
                {
                    "room": room.name,
                    "fo_status": room.occupancy_state,
                    "housekeeping": room.hk_status,
                }
                for room in rooms
                if (room.occupancy_state == "occupied" and room.hk_status == "clean")
                or (room.occupancy_state != "occupied" and room.hk_status == "dirty")
            ]
        elif self.report_type == "agency_advances":
            columns = [
                ("payment", "Payment"),
                ("agency", "Agency / Entity"),
                ("total", "Total"),
                ("available", "Available"),
                ("currency", "Currency"),
            ]
            # The report role is checked above and the elevated query remains
            # constrained to the already record-rule-checked property and the
            # single hotel payment purpose. This avoids requiring broad access
            # to accounting payments merely to print the approved summary.
            payments = (
                self.env["account.payment"]
                .sudo()
                .search(
                    [
                        ("hotel_property_id", "=", self.property_id.id),
                        ("hotel_payment_purpose", "=", "agency_advance"),
                        ("state", "in", ("in_process", "paid")),
                    ]
                )
            )
            rows = [
                {
                    "payment": payment.name,
                    "agency": payment.partner_id.name,
                    "total": payment.amount,
                    "available": payment.hotel_available_advance,
                    "currency": payment.currency_id.name,
                }
                for payment in payments
                if payment.hotel_available_advance
            ]
            summary = self._currency_summary(
                rows, (("total", "Total"), ("available", "Available"))
            )
        elif self.report_type == "pos_room_charges":
            columns = [
                ("date", "Date"),
                ("folio", "Folio"),
                ("guest", "Guest"),
                ("pos_receipt", "POS Receipt"),
                ("description", "Description"),
                ("untaxed", "Untaxed"),
                ("tax", "Tax"),
                ("total", "Total"),
                ("currency", "Currency"),
            ]
            start, end = self._day_window()
            lines = self.env["hotel.folio.line"].search(
                [
                    ("folio_id.property_id", "=", self.property_id.id),
                    ("source_type", "=", "pos"),
                    ("date", ">=", start),
                    ("date", "<", end),
                ]
            )
            rows = [
                {
                    "date": self._operational_datetime(line.date),
                    "folio": line.folio_id.name,
                    "guest": line.folio_id.partner_id.name,
                    "pos_receipt": line.source_reference or "",
                    "description": line.name,
                    "untaxed": line.amount_untaxed,
                    "tax": line.amount_tax,
                    "total": line.amount_total,
                    "currency": line.currency_id.name,
                }
                for line in lines
            ]
            summary = self._currency_summary(
                rows, (("untaxed", "Untaxed"), ("tax", "Tax"), ("total", "Total"))
            )
        else:
            if not self.folio_id:
                raise UserError(_("Select a folio for the consolidated statement."))
            columns = [
                ("date", "Date"),
                ("source", "Source"),
                ("description", "Description"),
                ("accounting", "Accounting"),
                ("untaxed", "Untaxed"),
                ("tax", "Tax"),
                ("total", "Total"),
                ("currency", "Currency"),
            ]
            for line in self.folio_id.line_ids:
                accounting_move = (
                    line.invoice_line_id.move_id or line.accounting_move_id
                ).sudo()
                rows.append(
                    {
                        "date": self._western(line.service_date),
                        "source": line.source_reference
                        or dict(line._fields["source_type"].selection).get(
                            line.source_type
                        ),
                        "description": line.name,
                        "accounting": accounting_move.name or "",
                        "untaxed": line.amount_untaxed,
                        "tax": line.amount_tax,
                        "total": line.amount_total,
                        "currency": line.currency_id.name,
                    }
                )
            # A permitted folio statement exposes only the payments linked to
            # that already property-scoped folio; sudo avoids granting front
            # desk users broad account.payment access merely to print it.
            for payment in self.folio_id.sudo().payment_ids.filtered(
                lambda record: record.move_id.state == "posted"
            ):
                sign = -1.0 if payment.payment_type == "inbound" else 1.0
                rows.append(
                    {
                        "date": self._western(payment.date),
                        "source": self._label("Payment / Advance"),
                        "description": dict(
                            payment._fields["hotel_payment_purpose"].selection
                        ).get(payment.hotel_payment_purpose),
                        "accounting": payment.move_id.name or payment.name,
                        "untaxed": "",
                        "tax": "",
                        "total": sign * payment.amount,
                        "currency": payment.currency_id.name,
                    }
                )
            rows.sort(
                key=lambda row: (row["date"], row["accounting"], row["description"])
            )
            summary = [
                (self._label("Total"), self.folio_id.amount_total),
                (self._label("Invoiced / Transferred"), self.folio_id.amount_invoiced),
                (self._label("Paid"), self.folio_id.amount_paid),
                (self._label("Due"), self.folio_id.amount_due),
            ]
        title = dict(REPORT_TYPES)[self.report_type]
        return {
            "title": self._label(title),
            "columns": [(key, self._label(label)) for key, label in columns],
            "column_widths": self._column_widths(columns),
            "rows": rows,
            "rtl": self.language == "ar",
            "family": self._report_family(),
            "property": self.property_id.company_id.display_name,
            "date": self._western(self.date),
            "summary": summary,
        }

    def action_print(self):
        self.ensure_one()
        self._check_report_access()
        action_xmlid = REPORT_ACTIONS[self._report_family()]
        return self.env.ref(action_xmlid).report_action(self, config=False)

    def action_export_xlsx(self):
        self.ensure_one()
        self._check_report_access()
        return {
            "type": "ir.actions.act_url",
            "url": f"/hotel/reports/xlsx/{self.id}",
            "target": "self",
        }

    def _build_xlsx(self):
        self.ensure_one()
        payload = self._get_report_payload()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Report")
        if payload["rtl"]:
            worksheet.right_to_left()
        title_format = workbook.add_format(
            {"bold": True, "font_size": 16, "align": "center"}
        )
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#D9EAF7", "border": 1}
        )
        money_format = workbook.add_format(
            {"num_format": "[$-409]#,##0.000", "border": 1}
        )
        cell_format = workbook.add_format({"border": 1})
        column_count = max(len(payload["columns"]), 1)
        worksheet.merge_range(0, 0, 0, column_count - 1, payload["title"], title_format)
        worksheet.write(1, 0, payload["property"])
        worksheet.write(1, 1, payload["date"])
        for column, (_key, label) in enumerate(payload["columns"]):
            worksheet.write(3, column, self._western(label), header_format)
            worksheet.set_column(column, column, max(14, min(len(label) + 5, 30)))
        for row_index, row in enumerate(payload["rows"], start=4):
            for column, (key, _label) in enumerate(payload["columns"]):
                value = row.get(key, "")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    worksheet.write_number(row_index, column, value, money_format)
                else:
                    worksheet.write(
                        row_index, column, self._western(value), cell_format
                    )
        summary_row = 5 + len(payload["rows"])
        for offset, (label, value) in enumerate(payload["summary"]):
            worksheet.write(
                summary_row + offset, 0, self._western(label), header_format
            )
            worksheet.write_number(summary_row + offset, 1, value, money_format)
        workbook.close()
        return output.getvalue()
