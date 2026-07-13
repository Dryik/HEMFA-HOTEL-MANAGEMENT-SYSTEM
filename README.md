# HEMFA HOTEL MANAGEMENT SYSTEM — Odoo 19 Enterprise

Custom hotel property management addon suite (first deployment: Tubactus Hotel, Libya).
Deployment target: **Odoo.sh** using `dev` → `staging` → `main` promotion.
Repository: https://github.com/Dryik/HEMFA-HOTEL-MANAGEMENT-SYSTEM

See `docs/architecture_decisions.md`, `docs/release_workflow.md`, and the
phase acceptance documents under `docs/` for the locked production design.

## Modules

| Module | Phase | Status | Purpose |
|---|---|---|---|
| `hotel_base` | 2 | implemented | Property scope, roles, business-day service, PII protection, commission placeholders |
| `hotel_rate` | 5 | implemented | Deterministic seasonal/occupancy pricing and confirmed-rate locking |
| `hotel_reservation` | 4 | implemented | Availability service, lifecycle, immutable amendments, groups and rooming lists |
| `hotel_folio` | 3 | implemented; finance gate open | Tax-aware folio, routing, invoices, deposits/advances, FX audit and reversals |
| `hotel_night_audit` | 5 | implemented | Concurrency lock, audited-date posting, KPI snapshots and exact reversal/re-run |
| `hotel_frontdesk_session` | 3 | implemented | Explicit posted payments, per-journal/currency close and immutable snapshots |
| `hotel_restricted_services` | 3 | implemented | Property/day entity ceilings with row-lock concurrency control |
| `hotel_housekeeping` | 4 | implemented | Cleaning/discrepancy workflow with immutable completed records |
| `hotel_maintenance` | 4 | implemented | Room blocking and manager-verified immutable completion |
| `hotel_guest_services` | 4 | implemented | Lost-and-found, DND, and wake-up calls |
| `hotel_pos_room_charge` | 3 | implemented | Discount/tax parity, idempotent folio lines and clearing-to-receivable transfer |
| `hotel_board` | 5 | implemented | Property/date color room board with resilient 60-second refresh |
| `hotel_reports` | 6 | implemented | Bilingual PDF/XLSX operational, finance, audit and consolidated folio reports |
| `l10n_ly_hemfa` | 3 | blocked at signed finance gate | Reserved localization addon; intentionally non-installable until approved account/tax templates arrive |

## Conventions

- Odoo 19 Enterprise APIs only; `<list>` views, Owl 2 frontend.
- Company currency LYD; FX rate editable per invoice (client decision 2026-07-09).
- Hotel business day runs 12:00 → 12:00.
- All manager overrides tracked via chatter with reason.
- Every model change ships with access rules in the same commit.

## Local checks

```powershell
python scripts/validate_repository.py
```

The repository currently contains 98 tagged test methods across 13 addon test
suites. Runtime installation, upgrade, and tagged tests run on Odoo.sh; GitHub
Actions performs database-free static checks. See `docs/release_workflow.md`.

Migration tooling and acceptance runbooks live under `scripts/migration/` and
`docs/`. Finance-approved Libyan account/tax codes, Odoo.sh runtime evidence,
legacy data, performance/UAT execution, and signed acceptance remain external
release gates and are intentionally not fabricated in this repository.
