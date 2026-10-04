# Backup and restore runbook

The targets are a proposed **RPO of 24 hours and an RTO of 8 hours** (design section 9). They count as met only after a timed exercise on production-sized data.

## Schedule

| What | When | Keep |
|---|---|---|
| `backup.py backup` (database dump + objects + fingerprint) | Daily, outside working hours | 30 daily, 12 monthly |
| `backup.py verify` on the newest backup | After every backup | — |
| Restore exercise into a scratch environment | Quarterly, and after any schema migration | Record the duration and the result |
| PostgreSQL WAL archiving (point-in-time recovery) | Continuous, where the platform offers it | 7 days |

Copy backups off the host into encrypted storage, with access limited to operators. They contain research sequences.

## Restore

1. **Declare the incident.** Stop the API and the workers, so nothing writes to a half-restored system.
2. **Choose the backup.** Pick the newest backup that passes `backup.py verify`.
3. **Provision the targets.** Create an empty database and an empty bucket or directory, then point `SEQUENCE_VAULT_DATABASE_URL` and the storage settings at them.
4. **Restore.** Run `backup.py restore BACKUP_DIR`. Any reported difference means stop: try the previous backup and escalate.
5. **Check permissions.** Have a project administrator open 项目管理 and confirm members and roles. The fingerprint already compares grants, but people should confirm that the right people can work.
6. **Search spot check.** Search a few known records and compare them against the fingerprint counts in `manifest.json`.
7. **Restart.** Start the workers, then the API. Uploads left in progress after the backup point must be re-uploaded. Tell their owners: the audit log shows the last accepted upload per project.
8. **Record the exercise.** Note the timings (detection, restore, verification), the data-loss window and any follow-ups.

## After a rollback

When a restore or a legacy-cutover rollback replaces a newer database, first export every record created after the restore point. Use the records export in the web app, or `backup.py backup` of the newer database kept aside, so the new data can be re-entered and nothing is lost silently.

## Exercise log

| Date | Data size | Restore time | Result | Notes |
|---|---|---|---|---|
| 2026-10-01 | CI drill dataset (6 legacy rows, 1 source object) | seconds | Passed (fingerprints equal; tampering, non-empty target and missing object detected) | Production-sized exercise still required before the pilot |
