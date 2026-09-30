# Operations documentation boundary

Add deployment, incident response, policy/model/parser rollout and rollback, retention, backup, and recovery runbooks here as infrastructure is implemented.

Before launch, document source/evidence download authorization, parser CPU/memory/time/network isolation, antivirus behavior, short-lived credentials, and organization-approved model region/retention/training/deletion settings. Fail closed when scanning or AI approval is unavailable. Ordinary telemetry may contain IDs, counts, durations, and error codes, not research sequences.

The proposed RPO is 24 hours and RTO is 8 hours; validate these with a recovery exercise. Policy rollbacks apply to new runs and never rewrite historical publication. Legacy cutover needs a read-only snapshot, dry run, full reconciliation, incremental freeze/sync, and preservation of records created after cutover during rollback.
