# Departmental UAT Acceptance

Run every script with migrated staging data in Arabic and English. Record tester, date, property, evidence link, defects, retest, and signature.

| Department | Required acceptance scenarios |
|---|---|
| Front desk | Individual and group booking, availability, check-in, room move, extension, shortening, day use, DND, wake-up call, no-show, cancellation, settlement-controlled checkout |
| Cashier | Open session, posted receipt, refund, payout, multi-currency counts, journal/currency reconciliation, immutable close |
| Housekeeping | Checkout-created cleaning task, DND visibility, clean/inspect flow, discrepancy review, no PII export |
| Maintenance | Blocking request, room removal from availability, repair, verification, inventory restoration |
| F&B | POS sale, fiscal-position tax, discount, room-charge eligibility, blocked service, clearing transfer, receipt/folio drill-down |
| Accounting | Taxed invoice, deposit, agency advance, partial allocation, credit note, manual FX approval, reconciliation, debtor and advance reports |
| Manager | Reasoned checkout override, amendment/repricing approval, audit reversal/rerun, cross-role report review |

Acceptance requires zero unexplained accounting differences and no cross-property or cross-role data leakage.
