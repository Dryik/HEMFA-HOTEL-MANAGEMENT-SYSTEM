# Departmental UAT Acceptance

Run every script with migrated staging data in Arabic and English. Record tester, date, property, evidence link, defects, retest, and signature.

| Department | Required acceptance scenarios |
|---|---|
| Front desk | Dashboard and 7/14/30-day Planning tape; individual and group booking; empty-cell booking defaults; availability; check-in; room move; extension; shortening; day use; DND; wake-up call; no-show; cancellation; settlement-controlled checkout |
| Cashier | Open session, posted receipt, refund, payout, multi-currency counts, journal/currency reconciliation, immutable close |
| Housekeeping | Checkout-created cleaning task, DND visibility, clean/inspect flow, discrepancy review, no PII export |
| Maintenance | Blocking request, room removal from availability, repair, verification, inventory restoration |
| F&B | POS sale, fiscal-position tax, discount, room-charge eligibility, blocked service, clearing transfer, receipt/folio drill-down |
| Accounting | Taxed invoice, deposit, agency advance, partial allocation, credit note, manual FX approval, reconciliation, debtor and advance reports |
| Manager | Reasoned checkout override, amendment/repricing approval, audit reversal/rerun, cross-role report review |

Acceptance requires zero unexplained accounting differences and no cross-property or cross-role data leakage.

## Front Desk visual and interaction matrix

Run the Dashboard and Planning scripts at 1440 x 900 and 1024 x 768 in Arabic
RTL and English LTR. The signed evidence set must cover Front Desk Agent,
Supervisor, Cashier, Housekeeping, Maintenance, Accountant, and Manager access.

- Verify loading, empty, selected, attention, stale, retry, and recovered states.
- Verify occupied + dirty + DND, occupied + wake-up, vacant + maintenance,
  house-use, and out-of-order combinations without color-only meaning.
- Verify keyboard-only navigation, visible focus, screen-reader labels, and 44 px
  touch targets; repeat the core flow with tablet touch input.
- Verify property and business-date persistence through Dashboard, Planning,
  drill-downs, and new reservations, including a failed refresh.
- Verify the custom tape has no drag/resize affordance and that the native Gantt
  fallback cannot mutate a reservation.
- Verify 60-second background refresh preserves filters, focus, selection, and
  scroll, pauses in a background tab, and reports its last successful timestamp.

Every run records browser/version, viewport, language/direction, role, property,
business date, tester, evidence link, defect/retest result, and sign-off.
