# Legacy Migration Source Schema

The repeatable importer is `scripts/migration/legacy_migrator.py`. It consumes a UTF-8 JSON object and requires a stable `legacy_id` on every row. A dry run is mandatory before every committed run; dry runs execute normal ORM validation and roll back all writes.

Import order is properties, room types, floors, rooms, partners, reservations, folios, folio lines, receivables, and payments. Relational keys use names such as `property_legacy_id`, `guest_legacy_id`, and `room_legacy_id`. Products and taxes must already exist by approved product code and tax name; the importer rejects unknown values rather than inventing financial mappings.

The result is JSON-serializable and contains per-model created/updated counts, row-level errors, warnings, source counts, and final sequence positions. External IDs are written under the `hotel_legacy` namespace, making reruns idempotent. Duplicate legacy keys are rejected. Any row error rolls back the complete run after all rows have been checked, so a committed import is atomic.

`receivables` require `property_legacy_id`, `folio_legacy_id`, `partner_legacy_id`, `journal_code`, `invoice_date`, optional `currency`, and a `lines` array. Every line requires `folio_line_legacy_id` and `product_code`, with optional quantity, unit price, discount, and `tax_codes`. This mandatory folio-line link makes the native invoice residual and operational folio reconcile to the same charges.

`payments` require property and partner legacy IDs, an approved cash/bank `journal_code`, date, positive amount, and a hotel purpose (`guest_deposit`, `agency_advance`, `folio_settlement`, `refund`, or `payout`). `folio_legacy_id` is optional for unallocated agency advances. Optional `allocate_receivable_legacy_ids` reconciles the posted native payment with the listed imported invoices; company, partner, and currency must match.

Finance sections may be supplied only after the signed finance map identifies journals, taxes, partners, currencies, and the opening-balance date. Missing or inactive mappings are hard row errors. The importer never creates an account, tax, journal, currency, product, or synthetic payment assignment.

`sequence_maxima` accepts `sequence_code` plus a non-negative integer `maximum` for `hotel.reservation` and `hotel.folio`. These values must come from the signed legacy numbering inventory. Imported accounting document names are validated separately in staging because Odoo accounting uses journal/date sequence rules rather than these hotel `ir.sequence` records.
