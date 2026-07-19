# Hotel Menu Map

This document describes the effective Hotel app menu after `hotel_board` composes
the donor-module menus. Donor modules keep non-colliding root sequences so an
installation without `hotel_board` still degrades into a predictable order.

## Composition rules

- `hotel_board` owns the composed **Front Desk** dashboard/planning entries and
  the **Operations** workspace.
- Donor modules own their actions and security groups. Board overrides may move
  a menu or normalize its sequence, but do not broaden its groups.
- A role only sees entries allowed by both the menu and its ancestors. Manager
  implies supervisor, front desk, housekeeping, maintenance, F&B, and accountant.

## Effective tree by role

### Receptionist

- Front Desk: Dashboard, Planning, Arrivals Today, Departures Today, Reservations,
  Group Reservations, Folios, Reservation Amendments
- Online Bookings
- Operations: Maintenance
- Guests; Agencies / Entities
- Guest Services: Service Orders, Meals to Prepare, Do Not Disturb, Wake-up Calls,
  Lost and Found, Guest Ratings
- Reporting: Reports

### Front Office Supervisor

- Everything available to Receptionist
- Front Desk: Entity Service Ceilings
- Operations: Housekeeping Tasks, Discrepancies, Maintenance

### Housekeeping

- Operations: Housekeeping Tasks, Discrepancies, Maintenance
- Guest Services: Do Not Disturb, Lost and Found
- Reporting: Reports

### Maintenance

- Operations: Maintenance

### F&B

- Guest Services: Service Orders, Meals to Prepare

### Accountant

- Front Desk: Folios
- Agencies / Entities; Agency Commissions
- Reporting: Reports

### Manager

- All role menus above
- Reporting: Reports, Booking Analysis, Owner Dashboard
- Configuration: Property (including the Rooms inventory), Pricing, Services,
  Housekeeping, Billing, and technical entries supplied by installed modules

## Root order without `hotel_board`

Front Desk (10), Online Bookings (20), Guests (50), Agencies / Entities (60),
Agency Commissions (70), Guest Services (80), Housekeeping (90), Maintenance
(100), Reporting (110), Configuration (120). Rooms is under Configuration →
Property. Without `hotel_board`, Reporting
contains Reports and Booking Analysis; the board adds Owner Dashboard. Empty or
unauthorized entries are hidden by Odoo.

## Related workflow reference

See [Hotel State-Machine Glossary](state_glossary.md) for every workflow state,
stored key, and user-facing label.
