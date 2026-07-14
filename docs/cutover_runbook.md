# Cutover, Rollback, and Outage Runbook

1. Freeze legacy entry and record the exact cutoff business date/time.
2. Take and verify the pre-cutover database backup; retain it until final finance sign-off.
3. Export signed source totals, sequence maxima, open stays, folios, receivables, deposits, and advances.
4. Run the migration dry run, resolve every error, then run the committed import once.
5. Reconcile rooms, occupancy, room revenue, POS, cash, receivables, deposits, advances, and sequence next values.
6. Execute the signed role-based smoke scripts and performance gate.
7. Promote `dev → staging → main`, tag the release, and record deployed commit/database backup IDs.

Rollback is mandatory when unexplained financial differences remain, critical role isolation fails, room availability is unreliable, or the production database cannot be restored inside the agreed window. Restore the verified backup, return users to the legacy process, preserve failed-import diagnostics, and obtain a new go-live approval.

During an outage, use numbered paper registration and payment sheets. Record company, business date, operator, guest/stay reference, taxes, currency, payment method, and signatures. On recovery, a supervisor enters records in original sequence and accounting reconciles delayed payments before normal operations resume. Test primary and secondary internet paths during rehearsal.
