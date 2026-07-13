# Production Architecture Decisions

Baseline: commit `3879640` on Odoo 19 Enterprise.

## Locked decisions

- One Odoo company with property-scoped hotel records, explicit user property assignments, and property membership on hotel guest/entity master records.
- LYD is the company currency. Odoo Accounting owns invoices, taxes, payments, credits, receivables, and FX.
- Folios are an operational subledger and consolidated guest/entity statement.
- POS room-charge sales recognize revenue once. The room-charge payment method uses a clearing account that is transferred to the routed guest/entity receivable.
- The hotel business day is property-local noon to noon and is converted to UTC by one shared helper.
- Odoo.sh runs installation, upgrade, and tagged addon tests. GitHub Actions runs repository-only static checks.
- Branch promotion is `dev` to `staging` to `main`; `main` is production.
- Existing document sequences continue from verified legacy maxima.
- Legacy imports are idempotent and atomic: any structured row reject rolls back the complete run.
- Arabic reports use Western digits. XLSX output uses the bundled `xlsxwriter` package.
- Reception uses Arabic RTL by default while room numbers, dates, references, and
  monetary values remain Western-digit operational identifiers.
- `hotel_board` is the final staff-workspace composition addon. Its Dashboard and
  Planning APIs aggregate authoritative records without storing a second copy of
  hotel state.
- The primary reservation planner is a complete-room Owl inventory tape. Native
  Gantt remains a read-only fallback; reservation and housekeeping state changes
  must use their audited server actions rather than drag-and-drop.
- Initial performance acceptance covers 500 rooms and 50 concurrent users.

## Explicit deferrals

Portal, online booking, channel manager, spa, events, loyalty, key cards, OCR, advanced revenue management, and meal costing are outside the production MVP.

## Change control

Every schema change must bump the addon version, include an upgrade script when stored data is affected, add tagged tests, and pass the Odoo.sh staging upgrade before production promotion.
