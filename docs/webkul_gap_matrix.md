# HEMFA Webkul Feature-Parity Matrix — Sales-Free

This matrix is the acceptance inventory for the reviewed Webkul hotel demo. It
records behavioral parity, not a copy of Webkul's product-variant architecture.

| Reviewed capability | Status | HEMFA implementation |
|---|---|---|
| Companies / hotels | Existing | Native Odoo company or branch, synchronized private `hotel.property` configuration |
| Physical rooms and room status | Existing | `hotel.room`, Front Desk board, availability service |
| Archive-safe room history | Implemented | Archive-only rooms/floors/types, retirement metadata, linked product retirement |
| Facilities | Existing | `hotel.amenity`; no duplicate facilities model |
| Room-type service products | Existing | Native Odoo service products for taxes, accounts, and pricelists |
| Seasonal prices | Implemented | `hotel.seasonal.pricing`, weekday-aware nightly rules, Legacy Rates migration |
| Native pricelists without Sales | Implemented | Hotel Nightly Rate base on `product.pricelist.item`; no sales order |
| Nationality/residency prices | Existing / extended | Shared quote service used by back office and website |
| Adults, teenagers, children, infants | Implemented | Configurable age ranges, capacity/base occupancy, supplements |
| Immutable nightly price breakdown | Implemented | `hotel.reservation.rate.line`, locked at confirmation |
| Entire-stay and per-night charging | Implemented | Property policy plus idempotent scheduled posting |
| Folio | Existing / extended | Native hotel ledger retained; combined or isolated accounting documents |
| Paid/free and meal services | Implemented | `hotel.service`, allotted-service workflow, meal queue and KPI |
| Guest identity documents | Implemented | Private typed documents, verification, expiry, restricted portal download |
| Housekeeping teams/checklists/photos | Implemented | Teams, templates/results, triggers, deadlines, supervisors, before/after photos |
| Pre-arrival and checkout housekeeping | Implemented | Idempotent scheduled and checkout-generated tasks |
| Front-desk KPIs and room cards | Existing / extended | Booking review, meal, housekeeping and payment-exception queues; capacity/rate/future bookings |
| Owner analytics | Implemented | Date/company-filtered KPIs, comparisons, trends, sources, room types, geography, customers |
| Booking source / responsible user | Implemented | Direct, Website, Agent, manual OTA, Other |
| Booking and rating analysis | Implemented | Pivot/graph views and moderated post-stay ratings |
| Booking communications | Implemented | Request, voucher, pre-arrival, room move, cancellation, receipt, checkout, feedback |
| Combined and isolated billing | Implemented | One combined invoice per currency or one invoice per room folio/payee |
| POS pay at checkout | Implemented | Searchable in-house guest/reservation/room dialog; existing clearing-to-receivable flow |
| Public hotel pages | Implemented | Editable Odoo-theme Home, Rooms, Details, Facilities, Gallery, Policies, Contact |
| Multi-room public booking | Implemented | Sales-free basket and shared reservation group with physical-room assignments |
| Manual approval and online payment | Implemented | Manual, fixed deposit, percentage, or full payment policies |
| Atomic payment holds | Implemented | Multi-room advisory/row locks, blocking `pending_payment`, configurable expiry |
| Late/duplicate payment safety | Implemented | Idempotent callback handling and `payment_exception`; no unavailable re-creation |
| Group payment allocation | Implemented | Immutable `hotel.payment.allocation` across folios |
| Portal booking history | Implemented | Status, payment, folios, secure documents, policy-controlled cancellation |
| English / Arabic / RTL / mobile | Implemented | Complete Arabic addon catalogs, translatable fields/templates, Bootstrap responsive layout, and explicit RTL styling; rendered-device QA remains a staging check |
| Cross-company and public-route security | Implemented | Website-company scoping, signed tokens, CSRF, server repricing, private uploads |
| Sales orders / Sales app actions | Explicitly excluded | Automated validator rejects Sales dependencies, `sale.order`, Sales routes and menu/action references |
| OTA WebService accounts and synchronization | Explicitly excluded | Manual OTA remains a booking source only |
| Multi-hotel public metasearch | Explicitly excluded | One public hotel per Odoo website/company |
| Meetings / events | Explicitly excluded | Not implemented in the reviewed demo |

## Acceptance notes

- Website publication defaults to disabled on both the hotel and room types.
- Payment providers, document types, content, policies, and pricelists must be
  configured before publication.
- Runtime installation, true concurrent-session locking, real-provider callbacks,
  browser tours, and rendered Arabic/mobile evidence are collected on Odoo.sh
  staging; the repository validator supplies database-free structural,
  translation-completeness, and Sales-free assertions.
