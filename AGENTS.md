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
| `hotel_base` | 1 | done | Properties, floors, room types, rooms, amenities, guest/agency partner extensions |
| `hotel_reservation` | 1 | done (core) | Reservation lifecycle, Gantt tape chart, calendar, availability constraint |
| `hotel_board` | 1 | done (v1) | Front-desk KPI dashboard (Owl 2) |
| `hotel_folio` | 1-2 | implemented | Folio ledger, charge routing, deposits, invoicing |
| `hotel_rate` | 2a | implemented | Seasonal rates, occupancy bands, nationality pricing, rate lock |
| `hotel_night_audit` | 2a | implemented | Daily rollover: room-night posting, no-shows, occupancy snapshot |
| `hotel_frontdesk_session` | 2a | implemented | Cashier shift sessions, multi-currency cash counts |
| `hotel_housekeeping` | 3 | implemented | Cleaning tasks, dirty/clean/inspected flow, discrepancy wizard |
| `hotel_maintenance` | 3 | skeleton | Custom maintenance workflow (not yet implemented) |
| `hotel_restricted_services` | 2b | skeleton | Per-guest service blocklist (not yet implemented) |
| `hotel_pos_room_charge` | 4 | skeleton | POS charge-to-room (not yet implemented) |
| `hotel_reports` | 5 | skeleton | Arabic QWeb PDF + XLSX reports (not yet implemented) |

## Key Field Name Conventions

- `hotel.room.type`: Field is `code` (NOT `short_code`).
- `hotel.room`: Fields are `occupancy_state`, `hk_status`, `out_of_order`, `admin_use`.
- `hotel.reservation`: States are `draft`, `confirmed`, `checked_in`, `checked_out`, `cancelled`, `no_show`.
- `hotel.folio.line`: `payee_partner_id` determines who is billed.
- `hotel.frontdesk.session`: States are `opened`, `closed`.
- `hotel.night.audit`: States are `draft`, `done`.
- `hotel.housekeeping.task`: States are `draft`, `assigned`, `cleaning`, `clean`, `inspected`, `cancel`.

## Dependency Graph

```
hotel_base (foundation)
  ├── hotel_reservation (booking engine)
  │     ├── hotel_board (dashboard KPIs)
  │     ├── hotel_rate (dynamic pricing override)
  │     ├── hotel_housekeeping (auto-triggered on checkout)
  │     └── hotel_folio (auto-created on confirm)
  │           ├── hotel_frontdesk_session (cashier shifts)
  │           ├── hotel_night_audit (nightly rollover)
  │           ├── hotel_restricted_services (skeleton)
  │           │     └── hotel_pos_room_charge (skeleton)
  │           └── hotel_reports (skeleton)
  └── hotel_maintenance (skeleton)
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
| `hotel_base` | 4 tests |
| `hotel_reservation` | 11 tests |
| `hotel_folio` | 6 tests |
| `hotel_rate` | 7 tests |
| `hotel_night_audit` | 4 tests |
| `hotel_frontdesk_session` | 4 tests |
| `hotel_housekeeping` | 7 tests |
| **Total** | **43 tests** |

## Local Checks

```
python -m py_compile $(git ls-files '*.py')
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

## Odoo 19 Source Reference

Full Odoo 19 Enterprise source is at `odoo-19.0+e.20260711/` (gitignored, local dev reference only). Key locations:
- `odoo/orm/models.py` — ORM model base class
- `odoo/orm/fields.py` — All field types
- `odoo/orm/decorators.py` — `@api` decorators
- `odoo/orm/domains.py` — Domain class
- `odoo/orm/table_objects.py` — `Constraint`, `Index`, `UniqueIndex`
- `odoo/addons/base/models/ir_actions.py` — Action models
- `odoo/addons/base/models/ir_ui_view.py` — View validation
- `odoo/tests/common.py` — Test framework
