---
name: odoo-19
description: Use when editing, creating, or reviewing Odoo 19 addon code (Python models, XML views, tests, manifests, security files) for the HEMFA Hotel Management System. Covers Odoo 19 ORM, view XML syntax, test framework, and project conventions.
---

# Odoo 19 Development Skill

Use this skill when working on any Odoo 19 addon code in this project. It contains all Odoo 19 API changes, view syntax rules, test patterns, and project-specific conventions to prevent common mistakes.

## Critical Odoo 19 View XML Rules

### Always use `<list>`, never `<tree>`
```xml
<!-- CORRECT -->
<list string="Reservations">
    <field name="name"/>
</list>
<!-- WRONG — will fail validation -->
<tree string="Reservations">
    <field name="name"/>
</tree>
```

### `ir.actions.act_window` uses `res_model`, NOT `model`
```xml
<!-- CORRECT -->
<record id="my_action" model="ir.actions.act_window">
    <field name="name">My Action</field>
    <field name="res_model">my.model</field>
    <field name="view_mode">list,form</field>
</record>
<!-- WRONG — will fail with "Invalid field 'model'" -->
<field name="model">my.model</field>
```

### `invisible`, `readonly`, `required` use Python expressions (NO `attrs`)
```xml
<!-- CORRECT -->
<field name="state" invisible="state == 'draft'"/>
<field name="date" readonly="state in ('cancelled', 'done')"/>
<field name="name" required="not id"/>

<!-- WRONG — will fail with "attrs is no longer used" -->
<field name="state" attrs="{'invisible': [('state', '=', 'draft')]}"/>
```

### `column_invisible` for hiding list columns
```xml
<!-- CORRECT — hides column but keeps data for decoration -->
<field name="id" column_invisible="True"/>
<field name="currency_id" column_invisible="1"/>

<!-- WRONG — this hides individual cells, not the column -->
<field name="id" invisible="1"/>
```

### Kanban template names
```xml
<!-- CORRECT -->
<templates>
    <t t-name="card">...</t>
    <t t-name="menu">...</t>
</templates>

<!-- WRONG — old names no longer valid -->
<t t-name="kanban-box">...</t>
<t t-name="kanban-menu">...</t>
```

## Python ORM Rules

### `_sql_constraints` removed — use `models.Constraint()`
```python
# CORRECT
_name_unique = models.Constraint('UNIQUE(name)', 'Name must be unique')
_amount_check = models.Constraint('CHECK(amount > 0)', 'Amount must be positive')

# WRONG — will log warning and be ignored
_sql_constraints = [('unique_name', 'UNIQUE(name)', 'Name must be unique')]
```

### Index creation
```python
# CORRECT
_property_type_idx = models.Index('(property_id, room_type_id)')

# WRONG
_sql_constraints = [...]  # removed in Odoo 19
```

### `create()` always receives list of dicts
```python
@api.model_create_multi
def create(self, vals_list):
    # vals_list is always a list, even for single record
    records = super().create(vals_list)
    return records
```

### Deprecated patterns to avoid
- `self._cr` → use `self.env.cr`
- `self._uid` → use `self.env.uid`
- `self._context` → use `self.env.context`
- `check_access_rights()` → use `check_access()`
- `read_group()` → use `_read_group()` or `formatted_read_group()`
- `group_operator` → use `aggregator`
- `lazy_property` → use `functools.cached_property`
- `odoo.osv.expression` → use `odoo.fields.Domain`
- `type='json'` in routes → use `type='jsonrpc'`
- `force_company` context key → use `with_company(company)`
- `toggle_active()` → use `action_archive()` / `action_unarchive()`
- `_check_recursion()` → use `_has_cycle()`

## Test Framework Rules

### Import pattern
```python
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
```

### setUpClass pattern
```python
class TestMyFeature(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()  # ALWAYS call super first
        cls.property = cls.env['hotel.property'].create({
            'name': 'Test Hotel',
        })
```

### Tag most tests as post_install
```python
from odoo.tests import tagged

@tagged('post_install', '-at_install')
class TestMyFeature(TransactionCase):
    ...
```

### Common assertions
```python
self.assertEqual(actual, expected)
self.assertTrue(value)
self.assertFalse(value)
self.assertIn(item, container)
with self.assertRaises(UserError):
    record.action_do_something()
```

## `__manifest__.py` Data Load Order

**CRITICAL:** XML files load in the order listed in the `data` list. If a menu references an action, the action's XML file MUST come BEFORE the menu's XML file.

```python
'data': [
    'security/ir.model.access.csv',     # 1. Security first
    'data/ir_sequence_data.xml',        # 2. Sequence data
    'views/my_model_views.xml',         # 3. Views (define actions)
    'wizard/my_wizard_views.xml',       # 4. Wizard views (if menus reference them)
    'views/my_menus.xml',              # 5. Menus LAST (reference actions above)
],
```

## Project-Specific Field Names

- `hotel.room.type`: Field is `code` (NOT `short_code`)
- `hotel.room`: `occupancy_state`, `hk_status`, `out_of_order`, `admin_use`
- `hotel.reservation`: States: `draft`, `confirmed`, `checked_in`, `checked_out`, `cancelled`, `no_show`
- `hotel.folio`: States: `draft`, `open`, `closed`
- `hotel.frontdesk.session`: States: `opened`, `closed`
- `hotel.night.audit`: States: `draft`, `done`
- `hotel.housekeeping.task`: States: `draft`, `assigned`, `cleaning`, `clean`, `inspected`, `cancel`
