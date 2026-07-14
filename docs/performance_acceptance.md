# Performance Acceptance Profile

The staging volume is at least 500 rooms, 5,000 partners, 100,000 reservations, and 50 concurrent authenticated users.

| Workload | Gate |
|---|---:|
| Room board and availability p95 | < 2 seconds |
| Front Desk Dashboard initial usable render and refresh p95 | < 2 seconds |
| Planning tape initial usable render and refresh p95 (30 days) | < 2 seconds |
| Common reservation and payment actions p95 | < 2 seconds |
| Full-occupancy daily operations report | < 5 minutes |
| Interactive PDF report | < 10 seconds |
| Large XLSX export | < 60 seconds |

Capture Odoo worker count, database sizing, cache state, dataset commit, request count, median, p95, p99, error rate, slow SQL, and explain plans. A result is invalid if record rules are bypassed, caches are prewarmed differently from production, or the 50 users share one session.

The Planning dataset must include every active room, at least 30 business days,
realistic overlapping reservation density, blockers, and guest-service alerts.
During refresh profiling, assert that filters, selection, keyboard focus, and both
scroll axes retain their positions.
