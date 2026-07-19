# Corporate Billing Policy

## Per-stay corporate billing

Corporate billing is selected per stay. A guest's **Default Agency / Entity**
(`res.partner.hotel_agency_id`) seeds the reservation, while the reservation's
`agency_id` is the authoritative entity for that stay. Folio routing then sets
each charge line's `payee_partner_id`; guest and entity invoices select only
their own lines.

The partner hierarchy is not a billing-policy shortcut. Use `parent_id` only
for genuine corporate contacts such as coordinators and representatives. Odoo
rolls a child contact's personal receivable up to its commercial parent, so
placing ordinary hotel guests under a company merely to express sponsorship
can incorrectly move their personal invoices to that company.

## Parent-company default

When a hotel guest is a person whose parent is an Agency / Entity, the parent
is automatically proposed and saved as the guest's Default Agency / Entity if
that field is empty. An explicitly selected default is never replaced. The
reservation may still choose a different entity for an individual stay.

## Entity service ceilings

Each ceiling defines what happens when a routed charge exceeds the entity's
remaining property/business-day allowance:

- **Block** preserves the supervisor-override workflow and logs the reason.
- **Charge guest for excess** keeps the allowed portion on the entity and
  routes the rounded remainder to the stay's guest. If the allowance is fully
  consumed, the whole charge is routed to the guest.

The policy is applied at the common folio charge entry point, including manual
charges, service workflows, and POS room charges.
