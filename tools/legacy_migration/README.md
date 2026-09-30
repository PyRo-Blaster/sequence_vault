# Separate legacy migration workflow

Implement read-only export, dry-run QC, anomaly review, reconciliation, and cutover helpers here. Preserve legacy IDs, original names, permissions, timestamps, and batch IDs. Use `source=legacy_import` when originals are unavailable; never fabricate evidence. Reconcile counts, hashes, rejected items, and permissions before cutover.
