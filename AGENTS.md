# HEMFA Hotel Management System — Project Memory

## Overview

Odoo 19 Enterprise addon suite — Hotel Property Management System (PMS).
First deployment: Tubactus Hotel, Libya.
Deployment target: Odoo.sh (dev / staging / production branches).

## Project Conventions

- **Currency:** LYD (Libyan Dinar); FX rate editable per invoice.
- **Business day:** 12:00 → 12:00 (noon-to-noon).
- **Manager overrides:** All tracked via chatter with reason.
- **Security:** Every model change ships with access rules in the same commit.
- **Views:** Odoo 19 `<list>` (NOT `<tree>`), Owl 2 frontend.
- **License:** OPL-1.
- **Author:** HEMFA.

## Module Structure & Status

| Module | Phase | Status | Purpose |
|---|---|---|---|
| `hotel_base` | 1 | done | Company-scoped hotel configuration, floors, room types, rooms, amenities, guest/agency partner extensions |
| `hotel_folio` | 3 | implemented (finance approval pending) | Tax-aware folio, native accounting, deposits/advances, FX, credits/reversals |
| `hotel_restricted_services` | 3 | implemented | Property/business-day aggregate ceilings with row locking |
| `hotel_pos_room_charge` | 3 | implemented | Idempotent discounted/taxed folio transfer from clearing to receivable |
| `l10n_ly_hemfa` | 3 | gated; not installable | Finance-approved Libyan chart, taxes and hotel accounting templates; intentionally disabled until sign-off |
| `hotel_reservation` | 4 | implemented | Shared availability, physical occupancy, amendments, groups and rooming lists |
| `hotel_housekeeping` | 4 | implemented | Cleaning/discrepancy workflow with immutable completion |
| `hotel_maintenance` | 4 | implemented | Maintenance workflow and verified immutable room-block release |
| `hotel_guest_services` | 4 | implemented | Guest operations, allotted services, documents and ratings |
| `hotel_rate` | 5 | implemented | Deterministic seasonal/occupancy/pricelist pricing and confirmed-rate lock |
| `hotel_website_booking` | 5 | implemented | Sales-free public/portal multi-room booking, online payments and booking analysis |
| `hotel_board` | 5 | implemented | Front Desk composition workspace, operational KPIs, attention queues and complete-room Planning tape |
| `hotel_reports` | 6 | implemented | Bilingual PDF/XLSX operational, finance and folio reports |
| `hotel_night_audit` | retired | migration tombstone | Empty installable shell for databases upgrading from the removed daily-rollover workflow |
| `hotel_frontdesk_session` | retired | migration tombstone | Empty installable shell for databases upgrading from the removed cashier-session workflow |

Retain both tombstones while any supported database may still have either legacy
module installed or queued for upgrade. They can be dropped only after the
migration inventory confirms every supported database reports the modules as
uninstalled/absent and no upgrade script or release path references their
technical names.

## Key Field Name Conventions

- `hotel.room.type`: Field is `code` (NOT `short_code`).
- `hotel.room`: Fields are `occupancy_state`, `hk_status`, `out_of_order`, `admin_use`.
- `hotel.reservation`: States are `draft`, `pending_payment`, `confirmed`, `checked_in`, `checked_out`, `cancelled`, `no_show`.
- `hotel.reservation.amendment`: States are `draft`, `applied`, `rejected`; applied/rejected records are immutable and undeletable.
- Configuration menus hang off section parents in `hotel_base`: `menu_hotel_config_section_property` / `_pricing` / `_services` / `_housekeeping` / `_billing`.
- `hotel.folio.line`: `payee_partner_id` determines who is billed.
- `hotel.housekeeping.task`: States are `new`, `cleaning`, `cleaned`, `cancel`.
- `hotel.maintenance.request`: States are `new`, `confirmed`, `in_progress`, `done`, `verified`, `cancel`; blocking starts at `confirmed`, verify needs `group_hotel_manager`.
- `hotel.service.restriction`: `restriction_type` is `blocked` or `limited` (with `daily_limit` / `stay_limit`); enforcement lives in `hotel.folio.add_charge`.
- `hotel.entity.service.ceiling`: per-agency `daily_limit`, empty `product_id` (a `product.product`, not a category) = all services; `on_excess` is `block` or `charge_guest`. The per-stay `hotel.service.restriction` still scopes by `category_id`.
- `hotel.reservation`: has a stored related `company_id` (= `property_id.company_id`) so client-side m2o domains can filter by company; the multi-company record rules still route through `property_id.company_id`.

## Dependency Graph

```
hotel_base                <- base, mail, product, contacts
hotel_reservation         <- hotel_base, web_gantt
hotel_rate                <- hotel_reservation, product, account
hotel_folio               <- hotel_rate, account
hotel_housekeeping        <- hotel_reservation
hotel_maintenance         <- hotel_base
hotel_guest_services      <- hotel_folio
hotel_restricted_services <- hotel_folio
hotel_pos_room_charge     <- hotel_folio, hotel_restricted_services, point_of_sale
hotel_reports             <- hotel_housekeeping, hotel_pos_room_charge
hotel_website_booking     <- hotel_rate, hotel_guest_services,
                             website, portal, payment, account_payment
hotel_board               <- hotel_reservation, hotel_folio, hotel_housekeeping,
                             hotel_maintenance, hotel_guest_services, hotel_reports,
                             hotel_website_booking, web
l10n_ly_hemfa             <- account
hotel_night_audit         <- base (migration tombstone)
hotel_frontdesk_session   <- base (migration tombstone)
```

## Odoo 19 Breaking Changes — MUST FOLLOW

### View XML

1. **`<tree>` → `<list>`**: All list views MUST use `<list>` as root tag.
2. **`attrs` attribute REMOVED**: Use direct Python expressions on `invisible`, `readonly`, `required`.
   ```xml
   <!-- OLD (WRONG) -->
   <field name="x" attrs="{'invisible': [('state', '=', 'draft')]}"/>
   <!-- NEW (CORRECT) -->
   <field name="x" invisible="state == 'draft'"/>
   ```
3. **`states` attribute REMOVED**: Use `invisible` with Python expressions.
4. **`column_invisible`**: Use `column_invisible="True"` to hide columns in list views (NOT `invisible="1"`).
5. **`t-name="kanban-box"` → `t-name="card"`**: Kanban template names changed.
6. **`t-name="kanban-menu"` → `t-name="menu"`**: Kanban menu template name changed.

### Action Records

7. **`ir.actions.act_window`**: Field is `res_model` (NOT `model`).
   ```xml
   <!-- OLD (WRONG) -->
   <field name="model">hotel.reservation</field>
   <!-- NEW (CORRECT) -->
   <field name="res_model">hotel.reservation</field>
   ```

### Python ORM

8. **`_sql_constraints` → `models.Constraint()`**: Class attribute removed.
   ```python
   # OLD (WRONG)
   _sql_constraints = [('unique_name', 'UNIQUE(name)', 'Name must be unique')]
   # NEW (CORRECT)
   _name_unique = models.Constraint('UNIQUE(name)', 'Name must be unique')
   ```
9. **`odoo.osv` fully deprecated**: Use `odoo.fields.Domain` instead of `expression()`.
10. **`@api.model` on `create`** auto-wraps to `model_create_multi`: `create` always expects a list of dicts.
11. **`group_operator` → `aggregator`**: Field parameter renamed.
12. **`self._cr`/`_uid`/`_context`**: Deprecated; use `self.env.cr`/`self.env.uid`/`self.env.context`.
13. **`check_access_rights()` → `check_access()`**: Method renamed.
14. **`read_group()` → `_read_group()`/`formatted_read_group()`**: Deprecated.
15. **`force_company` context key removed**: Use `with_company(company)` instead.

### Controller/HTTP

16. **`type='json'` → `type='jsonrpc'`**: Route type renamed.

### Testing

17. **`odoo.tests.common.Form` → `odoo.tests.Form`**: Import path changed.
18. **`@tagged('post_install', '-at_install')`**: Most addon tests need this.
19. **`TransactionCase`**: `commit()`/`rollback()` are patched to raise — tests run in savepoints.
20. **`setUpClass`**: Always call `super().setUpClass()` first.

## Test Coverage

| Module | Tests |
|---|---|
| `hotel_base` | 20 tests |
| `hotel_board` | 17 tests |
| `hotel_reservation` | 19 tests |
| `hotel_folio` | 15 tests |
| `hotel_rate` | 12 tests |
| `hotel_guest_services` | 8 tests |
| `hotel_housekeeping` | 12 tests |
| `hotel_restricted_services` | 13 tests |
| `hotel_maintenance` | 13 tests |
| `hotel_pos_room_charge` | 10 tests |
| `hotel_reports` | 14 tests |
| `hotel_website_booking` | 13 tests |
| **Total** | **166 tests** |

## Local Checks

```powershell
python scripts/validate_repository.py
```

Runtime testing happens on the Odoo.sh dev branch (no local Odoo install).

## Past Build Failures & Fixes

1. **`Invalid field 'model' in 'ir.actions.act_window'`**: Changed to `res_model` in housekeeping views.
2. **`External ID not found: hotel_housekeeping_discrepancy_wizard_action`**: Wizard views loaded after menus that reference them — reordered `__manifest__.py` data list.
3. **`Invalid field 'short_code' in 'hotel.room.type'`**: Test used wrong field name — changed to `code`.
4. **`invisible="1"` on list columns**: Must use `column_invisible="True"` instead (Odoo 19 view validator).
5. **`rec.company_id` on `hotel.reservation`**: Model has no `company_id` — use `rec.property_id.company_id` instead.
6. **`rec.id._origin.id` pattern**: Wrong — `rec.id` is an int for saved records. Use `isinstance(rec.id, int)` check.
7. **Missing `@tagged` on test class**: All test classes need `@tagged('post_install', '-at_install')`.
8. **`groups_id` on `res.users`**: Odoo 19 field is `group_ids` (not `groups_id`). Create users with `group_ids` or assign groups via `res.groups.write({'user_ids': [(4, user_id)]})`.
9. **`total_transactions` stored compute returns 0**: When calling stored compute methods directly, flush + invalidate_recordset before reading to ensure cache coherence.
10. **`<group expand="0" string="Group By">` in search views**: Odoo 19 RelaxNG rejects `expand` (cascades into misleading "extra content: field" errors). Use a plain `<group>` of `<filter>` elements — see hotel_housekeeping search view for the valid pattern.
11. **`has_group()` is False for the test superuser**: Odoo 19 checks real group membership with no superuser shortcut, and the test runner's `__system__` user is in no hotel group. Any test exercising a `has_group`-gated action must create a user with the right `group_ids` and call `with_user()`.
12. **`report_action()` returns the layout configurator**: for an admin on a company with no `external_report_layout_id`, `ir.actions.report.report_action(docs)` returns the document-layout act_window instead of the report. Call `report_action(docs, config=False)`.
13. **`create_date` is the transaction start timestamp**: Postgres `now()` is frozen at transaction start, so in tests `create_date` predates any wall-clock `fields.Datetime.now()` value captured during the test. Never compare them; pin `create_date` via SQL UPDATE when a compute filters on it.
14. **PO entries without `#:` occurrence lines are silently dropped**: Odoo 19's `PoFileReader` (`odoo/tools/translate.py`) only yields translations from occurrence references (`model:...`, `model_terms:...`, `code:...`); code entries additionally need an `#. odoo-python` / `#. odoo-javascript` comment to be served at runtime. Never hand-write ar.po files — run `python generate_ar_po.py` (derives occurrences from the addon source; xmlid formats per `ir_model.py`: `model_<model>`, `field_<model>__<field>`, `selection__<model>__<field>__<value>`) after adding terms to the `TRANSLATIONS` dict in `translate_exported_po.py`. A server-side `trans_export` piped through `translate_exported_po.py` remains the higher-fidelity option for view/QWeb text blocks. msgids must byte-match the source strings (watch multi-line Python string concatenation).
15. **Client-side m2o `domain` strings cannot traverse relations**: the web domain evaluator only sees the record's own field values, and a Many2one is just its id there, so a dotted path like `domain="[('company_id', '=', property_id.company_id)]"` renders an empty term and throws `InvalidDomainError: Invalid domain representation`. Add the needed value as a (related) field on the model and reference it directly — the pricelist filter on `hotel.reservation` now uses its own `company_id` field. Server-side domains (record rules, `search`, search-view `filter_domain`) still support dotted paths.

## Odoo 19 Source Reference

Full Odoo 19 Enterprise source is at `../odoo-19.0+e.20260712/` (sibling of the repo, local dev reference only — ALWAYS check it before guessing an Odoo API or view external ID). Key locations:
- `odoo/orm/models.py` — ORM model base class
- `odoo/orm/fields.py` — All field types
- `odoo/orm/decorators.py` — `@api` decorators
- `odoo/orm/domains.py` — Domain class
- `odoo/orm/table_objects.py` — `Constraint`, `Index`, `UniqueIndex`
- `odoo/addons/base/models/ir_actions.py` — Action models
- `odoo/addons/base/models/ir_ui_view.py` — View validation
- `odoo/tests/common.py` — Test framework
