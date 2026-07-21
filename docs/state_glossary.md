# Hotel State-Machine Glossary

State keys are stable data and integration contracts. Do not rename them without
an explicit data migration. User-facing cancellations consistently display
**Cancelled**, whether the stored key is `cancel` or `cancelled`. Generic workflow
completion displays **Completed**; domain-specific outcomes remain explicit.

## Workflow state fields

| Model | Field | Stored key → user-facing label |
|---|---|---|
| `hotel.reservation` | `state` | `draft` → Draft; `pending_payment` → Pending Payment; `confirmed` → Confirmed; `checked_in` → Checked In; `checked_out` → Checked Out; `cancelled` → Cancelled; `no_show` → No Show |
| `hotel.reservation.amendment` | `state` | `draft` → Draft; `applied` → Applied; `rejected` → Rejected |
| `hotel.reservation.group` | `state` | `draft` → Draft; `confirmed` → Confirmed; `cancelled` → Cancelled |
| `hotel.seasonal.pricing` | `state` | `draft` → Draft; `active` → Active; `expired` → Expired |
| `hotel.housekeeping.task` | `state` | `new` → New; `cleaning` → Cleaning; `cleaned` → Cleaned; `cancel` → Cancelled |
| `hotel.maintenance.request` | `state` | `new` → New; `confirmed` → Confirmed; `in_progress` → In Progress; `done` → Completed; `verified` → Verified; `cancel` → Cancelled |
| `hotel.lost.found` | `state` | `found` → Found; `claimed` → Claimed; `disposed` → Disposed |
| `hotel.do.not.disturb` | `state` | `active` → Active; `ended` → Ended; `cancelled` → Cancelled |
| `hotel.wakeup.call` | `state` | `scheduled` → Scheduled; `completed` → Completed; `missed` → Missed; `cancelled` → Cancelled |
| `hotel.reservation.service` | `state` | `draft` → Draft; `confirmed` → Confirmed; `done` → Completed; `cancelled` → Cancelled |
| `hotel.guest.rating` | `state` | `draft` → Awaiting Feedback; `submitted` → Submitted; `approved` → Published; `rejected` → Rejected |
| `hotel.online.booking` | `state` | `draft` → Draft; `pending_review` → Pending Review; `held` → Held; `payment_pending` → Payment Pending; `confirmed` → Confirmed; `expired` → Expired; `cancelled` → Cancelled; `payment_exception` → Payment Exception |

## Related operational status fields

These selections describe room, ledger, or reconciliation status rather than an
independent business workflow.

| Model | Field | Stored key → user-facing label |
|---|---|---|
| `hotel.room` | `occupancy_state` | `vacant` → Vacant; `reserved` → Reserved; `occupied` → Occupied; `checkout` → Checked Out |
| `hotel.room` | `hk_status` | `clean` → Clean; `dirty` → Dirty; `inspected` → Inspected |
| `hotel.folio` | `reservation_state` | Related to `hotel.reservation.state`; it uses the reservation labels above and is shown as Stay Status |
| `hotel.folio.line` | `lock_state` | `unlocked` → Unlocked; `accounting` → Accounting; `pos` → POS; `reversal` → Reversal |
| `hotel.housekeeping.discrepancy.wizard.line` | `fo_occupancy` | `vacant` → Vacant; `reserved` → Reserved; `occupied` → Occupied; `checkout` → Checked Out |
| `hotel.housekeeping.discrepancy.wizard.line` | `hk_occupancy` | `vacant` → Vacant; `occupied` → Occupied |
| `hotel.housekeeping.discrepancy.wizard.line` | `hk_status` | `clean` → Clean; `dirty` → Dirty; `inspected` → Inspected |
