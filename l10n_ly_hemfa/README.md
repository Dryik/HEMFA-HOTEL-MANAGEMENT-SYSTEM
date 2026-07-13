# l10n_ly_hemfa finance gate

This is the reserved Odoo 19 localization addon for the approved Libyan chart
of accounts, tax templates, fiscal positions, and hotel-specific defaults.

It is intentionally `installable: False`. The repository has not received the
signed account codes, tax rates/accounts/grids, journal mapping, deposit and
advance treatment, or credit-note policy listed in
`docs/finance_mapping.md`. Inventing those values would create invalid
accounting data.

To release this addon, finance must approve the mapping, then implementation
must add Odoo 19 chart/tax template data, localization installation tests,
opening-balance reconciliation tests, Arabic labels, and set `installable` to
`True` in the same reviewed change.
