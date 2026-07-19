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
- Rooms; Guests; Agencies / Entities
- Guest Services: Service Orders, Meals to Prepare, Do Not Disturb, Wake-up Calls,
  Lost and Found, Guest Ratings
- Reports

### Front Office Supervisor

- Everything available to Receptionist
- Operations: Housekeeping (Tasks, Discrepancy), Maintenance

### Housekeeping

- Operations: Housekeeping (Tasks, Discrepancy), Maintenance
- Rooms
- Guest Services: Do Not Disturb, Lost and Found
- Reports

### Maintenance

- Operations: Maintenance
- Rooms

### F&B

- Rooms
- Guest Services: Service Orders, Meals to Prepare

### Accountant

- Front Desk: Folios
- Rooms; Agencies / Entities; Agency Commissions
- Reports

### Manager

- All role menus above
- Owner Dashboard; Booking Analysis
- Configuration: Property, Pricing, Services, Housekeeping, Billing, and Technical
  configuration entries supplied by the installed modules

## Root order without `hotel_board`

Front Desk (10), Online Bookings (20), Rooms (40), Guests (50), Agencies / Entities
(60), Agency Commissions (70), Guest Services (80), Housekeeping (90), Maintenance
(100), Reports (110), Booking Analysis (115), Configuration (120). Empty or
unauthorized entries are hidden by Odoo.
