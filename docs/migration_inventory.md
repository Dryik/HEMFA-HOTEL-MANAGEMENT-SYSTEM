# Legacy Migration Inventory

Populate this document during source-system discovery. Every source must have an owner, extract date, stable legacy key, row count, and signed reconciliation total.

| Dataset | Stable key | Required totals/checks | Status |
|---|---|---|---|
| Properties/floors/rooms/types | Legacy code | Counts by property and status | Pending source extract |
| Guests and identity records | Guest number | Count, duplicates, missing IDs | Pending source extract |
| Agencies/entities | Entity number | Count and opening balance | Pending source extract |
| Future reservations | Reservation number | Count and value by arrival date | Pending source extract |
| In-house stays | Reservation number | Room, dates, rate, guest/entity | Pending source extract |
| Open folios | Folio number/line number | Untaxed, tax, total, paid, due | Pending source extract |
| Deposits/advances | Receipt number | Currency totals and unallocated residual | Pending source extract |
| Outstanding receivables | Invoice number | Currency and company-currency residual | Pending source extract |
| Document sequences | Document type | Highest valid legacy value | Pending source extract |

Migration tooling must support dry-run, idempotent re-run, structured rejects, legacy-ID traceability, and a machine-readable reconciliation summary.
