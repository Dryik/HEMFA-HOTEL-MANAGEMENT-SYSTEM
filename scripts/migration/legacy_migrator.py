"""Idempotent HEMFA legacy migration library for use from an Odoo shell.

Usage inside ``odoo-bin shell -d <database>``::

    exec(open("scripts/migration/legacy_migrator.py", encoding="utf-8").read())
    result = LegacyMigrator(env, "C:/migration/export.json", dry_run=True).run()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

The export is a JSON object containing arrays named ``properties``, ``room_types``,
``floors``, ``rooms``, ``partners``, ``reservations``, ``folios``, and
``folio_lines``. Every row requires a stable ``legacy_id``. Relational values use
the referenced row's legacy id (for example ``property_legacy_id``).
"""

from __future__ import annotations

import json
import hashlib
import re
from collections import Counter
from pathlib import Path

from odoo import Command, fields


class _DryRunRollback(Exception):
    pass


class _MigrationRejected(Exception):
    pass


class LegacyMigrator:
    MODULE = "hotel_legacy"

    def __init__(self, env, source_path, dry_run=True):
        self.env = env.sudo()
        self.source_path = Path(source_path)
        self.dry_run = dry_run
        self.source = json.loads(self.source_path.read_text(encoding="utf-8"))
        self.summary = Counter()
        self.errors = []
        self.warnings = []

    @staticmethod
    def _xmlid_name(model, legacy_id):
        raw = str(legacy_id)
        safe = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_").lower() or "record"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        return f"{model.replace('.', '_')}__{safe}__{digest}"

    @staticmethod
    def _legacy_xmlid_name(model, legacy_id):
        safe = re.sub(r"[^a-zA-Z0-9_]+", "_", str(legacy_id)).strip("_").lower()
        return f"{model.replace('.', '_')}__{safe}"

    def _lookup(self, model, legacy_id, required=True):
        names = [
            self._xmlid_name(model, legacy_id),
            self._legacy_xmlid_name(model, legacy_id),
        ]
        mapping = self.env["ir.model.data"].search(
            [("module", "=", self.MODULE), ("name", "in", names)], limit=1
        )
        record = self.env[model].browse(mapping.res_id).exists() if mapping else self.env[model]
        if required and not record:
            raise ValueError(f"Missing legacy reference {model}:{legacy_id}")
        return record

    def _upsert(self, model, legacy_id, values):
        record = self._lookup(model, legacy_id, required=False)
        if record:
            record.with_context(hotel_migration=True).write(values)
            self.summary[f"{model}.updated"] += 1
            return record
        record = self.env[model].with_context(hotel_migration=True).create(values)
        self.env["ir.model.data"].create(
            {
                "module": self.MODULE,
                "name": self._xmlid_name(model, legacy_id),
                "model": model,
                "res_id": record.id,
                "noupdate": True,
            }
        )
        self.summary[f"{model}.created"] += 1
        return record

    def _bind_external_id(self, model, legacy_id, record):
        self.env["ir.model.data"].create(
            {
                "module": self.MODULE,
                "name": self._xmlid_name(model, legacy_id),
                "model": model,
                "res_id": record.id,
                "noupdate": True,
            }
        )

    def _currency(self, code):
        currency = self.env["res.currency"].with_context(active_test=False).search(
            [("name", "=", code)], limit=1
        )
        if not currency:
            raise ValueError(f"Unknown currency {code}")
        if not currency.active:
            raise ValueError(f"Currency {code} must be activated before migration")
        return currency

    def _journal(self, company, code, allowed_types):
        journal = self.env["account.journal"].search(
            [
                ("company_id", "=", company.id),
                ("code", "=", code),
                ("type", "in", tuple(allowed_types)),
            ],
            limit=1,
        )
        if not journal:
            raise ValueError(
                f"Unknown approved journal {code} for {company.display_name}"
            )
        return journal

    def _run_rows(self, section, handler):
        seen_legacy_ids = set()
        for number, row in enumerate(self.source.get(section, []), start=1):
            legacy_id = row.get("legacy_id")
            try:
                if legacy_id in (None, ""):
                    raise ValueError("legacy_id is required")
                if legacy_id in seen_legacy_ids:
                    raise ValueError(f"duplicate legacy_id in {section}: {legacy_id}")
                seen_legacy_ids.add(legacy_id)
                with self.env.cr.savepoint():
                    handler(row)
            except Exception as exc:  # structured continuation is intentional
                self.errors.append(
                    {
                        "section": section,
                        "row": number,
                        "legacy_id": legacy_id,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )

    def _property(self, row):
        self._upsert(
            "hotel.property",
            row["legacy_id"],
            {
                "name": row["name"],
                "code": row.get("code"),
                "timezone": row.get("timezone", "Africa/Tripoli"),
                "current_business_date": row.get("current_business_date")
                or fields.Date.today(),
                "company_id": self.env.company.id,
            },
        )

    def _room_type(self, row):
        prop = self._lookup("hotel.property", row["property_legacy_id"], required=False)
        self._upsert(
            "hotel.room.type",
            row["legacy_id"],
            {
                "name": row["name"],
                "code": row.get("code"),
                "property_id": prop.id,
                "base_price": row.get("base_price", 0.0),
                "capacity_adults": row.get("capacity_adults", 2),
                "capacity_children": row.get("capacity_children", 0),
            },
        )

    def _floor(self, row):
        prop = self._lookup("hotel.property", row["property_legacy_id"])
        self._upsert(
            "hotel.floor",
            row["legacy_id"],
            {"name": row["name"], "property_id": prop.id, "sequence": row.get("sequence", 10)},
        )

    def _room(self, row):
        floor = self._lookup("hotel.floor", row["floor_legacy_id"])
        room_type = self._lookup("hotel.room.type", row["room_type_legacy_id"])
        self._upsert(
            "hotel.room",
            row["legacy_id"],
            {
                "name": row["name"],
                "floor_id": floor.id,
                "room_type_id": room_type.id,
                "telephone_extension": row.get("telephone_extension"),
                "admin_use": bool(row.get("admin_use")),
            },
        )

    def _partner(self, row):
        is_agency = bool(row.get("is_hotel_agency", False))
        values = {
            "name": row["name"],
            "is_hotel_guest": bool(row.get("is_hotel_guest", not is_agency)),
            "is_hotel_agency": is_agency,
            "email": row.get("email"),
            "phone": row.get("phone"),
            "guest_id_type": row.get("guest_id_type"),
            "guest_id_number": row.get("guest_id_number"),
            "guest_birthdate": row.get("guest_birthdate"),
            "ref": row.get("legacy_reference") or str(row["legacy_id"]),
        }
        self._upsert("res.partner", row["legacy_id"], values)

    def _reservation(self, row):
        prop = self._lookup("hotel.property", row["property_legacy_id"])
        guest = self._lookup("res.partner", row["guest_legacy_id"])
        room = self._lookup("hotel.room", row["room_legacy_id"], required=False)
        room_type = self._lookup("hotel.room.type", row["room_type_legacy_id"])
        agency = self._lookup("res.partner", row.get("agency_legacy_id"), required=False)
        guest._assign_hotel_property(prop)
        if agency:
            agency._assign_hotel_property(prop)
        values = {
            "name": row.get("name") or str(row["legacy_id"]),
            "partner_id": guest.id,
            "agency_id": agency.id,
            "property_id": prop.id,
            "room_type_id": room_type.id,
            "room_id": room.id,
            "checkin_date": row["checkin_date"],
            "checkout_date": row["checkout_date"],
            "actual_checkin": row.get("actual_checkin"),
            "actual_checkout": row.get("actual_checkout"),
            "rate_night": row.get("rate_night", 0.0),
            "adults": row.get("adults", 1),
            "children": row.get("children", 0),
            "state": row.get("state", "draft"),
        }
        self._upsert("hotel.reservation", row["legacy_id"], values)

    def _folio(self, row):
        reservation = self._lookup("hotel.reservation", row["reservation_legacy_id"])
        self._upsert(
            "hotel.folio",
            row["legacy_id"],
            {"name": row.get("name") or str(row["legacy_id"]), "reservation_id": reservation.id},
        )

    def _folio_line(self, row):
        folio = self._lookup("hotel.folio", row["folio_legacy_id"])
        product = self.env["product.product"].search(
            [("default_code", "=", row["product_code"])], limit=1
        )
        if not product:
            raise ValueError(f"Unknown product_code {row['product_code']}")
        payee = self._lookup("res.partner", row.get("payee_legacy_id"), required=False)
        values = {
            "folio_id": folio.id,
            "product_id": product.id,
            "name": row.get("description") or product.display_name,
            "date": row["date"],
            "service_date": row.get("service_date")
            or folio.property_id.get_business_date(row["date"]),
            "qty": row.get("qty", 1.0),
            "price_unit": row.get("price_unit", 0.0),
            "discount": row.get("discount", 0.0),
            "payee_partner_id": (payee or folio.partner_id).id,
            "source_type": "migration",
            "source_reference": row.get("legacy_reference") or str(row["legacy_id"]),
            "source_key": f"legacy:{row['legacy_id']}",
            "invoiceable": bool(row.get("invoiceable", True)),
            "tax_ids": [Command.set(self._tax_ids(row.get("tax_codes", [])))],
        }
        self._upsert("hotel.folio.line", row["legacy_id"], values)

    def _receivable(self, row):
        existing = self._lookup("account.move", row["legacy_id"], required=False)
        if existing:
            self.summary["account.move.reused"] += 1
            return existing
        prop = self._lookup("hotel.property", row["property_legacy_id"])
        folio = self._lookup("hotel.folio", row["folio_legacy_id"])
        partner = self._lookup("res.partner", row["partner_legacy_id"])
        partner._assign_hotel_property(prop)
        currency = self._currency(
            row.get("currency") or prop.company_id.currency_id.name
        )
        journal = self._journal(prop.company_id, row["journal_code"], {"sale"})
        source_lines = row.get("lines") or []
        if not source_lines:
            raise ValueError("A receivable requires at least one invoice line")
        invoice_line_values = []
        folio_lines = []
        for source_line in source_lines:
            folio_line = self._lookup(
                "hotel.folio.line", source_line["folio_line_legacy_id"]
            )
            if folio_line.folio_id != folio:
                raise ValueError("Invoice line references a different legacy folio")
            product = self.env["product.product"].search(
                [("default_code", "=", source_line["product_code"])], limit=1
            )
            if not product:
                raise ValueError(
                    f"Unknown product_code {source_line['product_code']}"
                )
            invoice_line_values.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": source_line.get("description")
                        or product.display_name,
                        "quantity": source_line.get("qty", 1.0),
                        "price_unit": source_line.get("price_unit", 0.0),
                        "discount": source_line.get("discount", 0.0),
                        "tax_ids": [
                            Command.set(
                                self._tax_ids(source_line.get("tax_codes", []))
                            )
                        ],
                    },
                )
            )
            folio_lines.append(folio_line)
        move = self.env["account.move"].with_company(prop.company_id).create(
            {
                "move_type": "out_invoice",
                "name": row.get("name") or "/",
                "ref": row.get("reference") or str(row["legacy_id"]),
                "partner_id": partner.id,
                "company_id": prop.company_id.id,
                "journal_id": journal.id,
                "currency_id": currency.id,
                "invoice_date": row["invoice_date"],
                "date": row.get("accounting_date") or row["invoice_date"],
                "hotel_property_id": prop.id,
                "hotel_folio_id": folio.id,
                "invoice_line_ids": invoice_line_values,
            }
        )
        self._bind_external_id("account.move", row["legacy_id"], move)
        folio._link_account_move(move)
        for folio_line, invoice_line in zip(
            folio_lines, move.invoice_line_ids, strict=True
        ):
            folio_line._link_invoice_line(invoice_line)
        if row.get("posted", True):
            move.action_post()
        self.summary["account.move.created"] += 1
        return move

    def _payment(self, row):
        existing = self._lookup("account.payment", row["legacy_id"], required=False)
        if existing:
            self.summary["account.payment.reused"] += 1
            return existing
        prop = self._lookup("hotel.property", row["property_legacy_id"])
        partner = self._lookup("res.partner", row["partner_legacy_id"])
        partner._assign_hotel_property(prop)
        folio = self._lookup(
            "hotel.folio", row.get("folio_legacy_id"), required=False
        )
        currency = self._currency(
            row.get("currency") or prop.company_id.currency_id.name
        )
        journal = self._journal(
            prop.company_id, row["journal_code"], {"bank", "cash"}
        )
        purpose = row.get("purpose", "guest_deposit")
        allowed_purposes = {
            "guest_deposit",
            "agency_advance",
            "folio_settlement",
            "refund",
            "payout",
        }
        if purpose not in allowed_purposes:
            raise ValueError(f"Unsupported hotel payment purpose {purpose}")
        payment_type = row.get("payment_type", "inbound")
        if row["amount"] <= 0:
            raise ValueError("Payment amount must be greater than zero")
        if purpose in {"guest_deposit", "agency_advance", "folio_settlement"} and (
            payment_type != "inbound"
        ):
            raise ValueError(f"{purpose} requires an inbound payment")
        if purpose in {"refund", "payout"} and payment_type != "outbound":
            raise ValueError(f"{purpose} requires an outbound payment")
        if purpose in {"folio_settlement", "refund"} and not folio:
            raise ValueError(f"{purpose} requires folio_legacy_id")
        payment = self.env["account.payment"].with_company(prop.company_id).create(
            {
                "payment_type": payment_type,
                "partner_type": "customer",
                "partner_id": partner.id,
                "amount": row["amount"],
                "currency_id": currency.id,
                "journal_id": journal.id,
                "date": row["date"],
                "memo": row.get("reference") or str(row["legacy_id"]),
                "hotel_property_id": prop.id,
                "hotel_folio_id": folio.id,
                "hotel_payment_purpose": purpose,
            }
        )
        self._bind_external_id("account.payment", row["legacy_id"], payment)
        if row.get("posted", True):
            payment.action_post()
        invoice_legacy_ids = row.get("allocate_receivable_legacy_ids", [])
        if invoice_legacy_ids:
            invoices = self.env["account.move"]
            for legacy_id in invoice_legacy_ids:
                invoices |= self._lookup("account.move", legacy_id)
            if invoices.filtered(
                lambda invoice: invoice.company_id != payment.company_id
                or invoice.currency_id != payment.currency_id
                or invoice.commercial_partner_id
                != payment.partner_id.commercial_partner_id
                or invoice.state != "posted"
            ):
                raise ValueError(
                    "Payment allocation requires posted invoices for the same company, currency, and partner"
                )
            receivable_lines = (payment.move_id | invoices).line_ids.filtered(
                lambda line: line.account_id.account_type == "asset_receivable"
                and not line.reconciled
            )
            if receivable_lines:
                receivable_lines.reconcile()
        self.summary["account.payment.created"] += 1
        return payment

    def _tax_ids(self, codes):
        taxes = self.env["account.tax"].search(
            [("company_id", "=", self.env.company.id), ("name", "in", codes)]
        )
        missing = set(codes) - set(taxes.mapped("name"))
        if missing:
            raise ValueError(f"Unapproved or unknown tax codes: {sorted(missing)}")
        return taxes.ids

    def _continue_sequences(self):
        mapping = {
            "hotel.reservation": "hotel.reservation",
            "hotel.folio": "hotel.folio",
            "hotel.night.audit": "hotel.night.audit",
        }
        for model, sequence_code in mapping.items():
            maxima = []
            for name in self.env[model].search([]).mapped("name"):
                numbers = re.findall(r"(\d+)", name or "")
                if numbers:
                    maxima.append(int(numbers[-1]))
            if maxima:
                sequence = self.env["ir.sequence"].search(
                    [("code", "=", sequence_code)], limit=1
                )
                if sequence and sequence.number_next_actual <= max(maxima):
                    sequence.number_next_actual = max(maxima) + 1
                    self.summary[f"sequence.{sequence_code}"] = max(maxima) + 1
        allowed_codes = set(mapping.values())
        for row in self.source.get("sequence_maxima", []):
            sequence_code = row.get("sequence_code")
            maximum = row.get("maximum")
            if sequence_code not in allowed_codes:
                self.errors.append(
                    {
                        "section": "sequence_maxima",
                        "row": sequence_code,
                        "legacy_id": sequence_code,
                        "error_type": "ValueError",
                        "message": f"Unsupported hotel sequence code {sequence_code}",
                    }
                )
                continue
            if not isinstance(maximum, int) or maximum < 0:
                self.errors.append(
                    {
                        "section": "sequence_maxima",
                        "row": sequence_code,
                        "legacy_id": sequence_code,
                        "error_type": "ValueError",
                        "message": "maximum must be a non-negative integer",
                    }
                )
                continue
            sequence = self.env["ir.sequence"].search(
                [("code", "=", sequence_code)], limit=1
            )
            if not sequence:
                self.errors.append(
                    {
                        "section": "sequence_maxima",
                        "row": sequence_code,
                        "legacy_id": sequence_code,
                        "error_type": "ValueError",
                        "message": f"Missing Odoo sequence {sequence_code}",
                    }
                )
                continue
            if sequence.number_next_actual <= maximum:
                sequence.number_next_actual = maximum + 1
            self.summary[f"sequence.{sequence_code}"] = sequence.number_next_actual

    def run(self):
        handlers = [
            ("properties", self._property),
            ("room_types", self._room_type),
            ("floors", self._floor),
            ("rooms", self._room),
            ("partners", self._partner),
            ("reservations", self._reservation),
            ("folios", self._folio),
            ("folio_lines", self._folio_line),
            ("receivables", self._receivable),
            ("payments", self._payment),
        ]
        try:
            with self.env.cr.savepoint():
                for section, handler in handlers:
                    self._run_rows(section, handler)
                self._continue_sequences()
                if self.errors:
                    raise _MigrationRejected()
                if self.dry_run:
                    raise _DryRunRollback()
        except _DryRunRollback:
            self.summary["dry_run_rolled_back"] = 1
        except _MigrationRejected:
            self.summary["rolled_back_due_to_errors"] = 1
        return {
            "source": str(self.source_path),
            "dry_run": self.dry_run,
            "summary": dict(self.summary),
            "errors": self.errors,
            "warnings": self.warnings,
            "reconciliation": {
                "properties": len(self.source.get("properties", [])),
                "rooms": len(self.source.get("rooms", [])),
                "partners": len(self.source.get("partners", [])),
                "reservations": len(self.source.get("reservations", [])),
                "folios": len(self.source.get("folios", [])),
                "folio_lines": len(self.source.get("folio_lines", [])),
                "receivables": len(self.source.get("receivables", [])),
                "payments": len(self.source.get("payments", [])),
                "sequence_maxima": len(self.source.get("sequence_maxima", [])),
            },
        }
