# HEMFA HOTEL MANAGEMENT SYSTEM — Odoo 19 Enterprise

Custom hotel property management addon suite (first deployment: Tubactus Hotel, Libya).
Deployment target: **Odoo.sh** (dev / staging / production branches).
Repository: https://github.com/Dryik/HEMFA-HOTEL-MANAGEMENT-SYSTEM

See `../implementation-plan-v3.md` for the full build plan and client decisions.

## Modules

| Module | Phase | Status | Purpose |
|---|---|---|---|
| `hotel_base` | 1 | **done** | Properties, floors, room types, rooms, amenities, guest/agency partner extensions, security groups, menus |
| `hotel_rate` | 2a | skeleton | Seasonal rates, occupancy bands, nationality→currency rule, 12:00→12:00 business day, rate lock |
| `hotel_reservation` | 1 | **done (core)** | Reservation lifecycle, Gantt tape chart, calendar, availability + exclusion constraint; groups/amendments pending |
| `hotel_folio` | 1–2 | skeleton | Folio ledger, charge routing matrix, deposits, invoicing (guest/entity/group) |
| `hotel_night_audit` | 2a | skeleton | Daily rollover: room-night posting, no-shows, occupancy snapshot, audit report |
| `hotel_frontdesk_session` | 2a | skeleton | Cashier shift sessions, multi-currency cash counts, shift-close report |
| `hotel_restricted_services` | 2b | skeleton | Per-guest service blocklist, per-entity daily ceilings, POS/service validation |
| `hotel_housekeeping` | 3 | skeleton | Cleaning tasks, dirty/clean/inspected flow, discrepancy report |
| `hotel_maintenance` | 3 | skeleton | Custom maintenance workflow, room out-of-order blocking |
| `hotel_pos_room_charge` | 4 | skeleton | POS "charge to room" payment method with folio validation |
| `hotel_board` | 1 | **done (v1)** | Front-desk KPI dashboard (landing page); full color room board pending |
| `hotel_reports` | 5 | skeleton | Arabic QWeb PDF + XLSX legacy reports |

## Conventions

- Odoo 19 Enterprise APIs only; `<list>` views, Owl 2 frontend.
- Company currency LYD; FX rate editable per invoice (client decision 2026-07-09).
- Hotel business day runs 12:00 → 12:00.
- All manager overrides tracked via chatter with reason.
- Every model change ships with access rules in the same commit.

## Local checks

```
python -m py_compile $(git ls-files '*.py')
```

Runtime testing happens on the Odoo.sh dev branch (no local Odoo install).
