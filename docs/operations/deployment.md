# Deployment and incident runbook

Topology and image requirements: [infrastructure/deployment](../../infrastructure/deployment/README.md). Commands below use `admin` for `python -m sequence_vault.entrypoints.admin`, run in the backend image with production settings.

## First installation

1. **Provision services.** PostgreSQL 17 and a private, versioned S3 bucket (or let the API create it in MinIO, `SEQUENCE_VAULT_OBJECT_STORAGE_CREATE_BUCKET=true`). Enable WAL archiving if the platform offers it.
2. **Provision ClamAV.** Run it with signature updates. Without a verdict, nothing is parsed (fail closed).
3. **Register the OIDC client.** Configure the proxy to set `X-Forwarded-Email` and to replace client-sent values.
4. **Generate the proxy secret.** Run `python -c "import secrets; print(secrets.token_urlsafe(32))"` and give it only to the web and API containers.
5. **Migrate.** Automatic when the API starts with `SEQUENCE_VAULT_MIGRATE_ON_START=true` (as in Compose); otherwise run `admin migrate`.
6. **Provision access.**
   - `admin create-tenant --name …` and `admin create-project --tenant … --name …`.
   - `admin add-user --tenant … --subject <sign-in email> --name …`.
   - `admin grant --project … --user … --role project_admin`.

   Project administrators manage everyone else in 项目管理.
7. **Start the services.** Start the API, then workers (at least 2; the job table supports more), then web and the proxy. With Compose this is `pull` then `up -d` ([infrastructure/local](../../infrastructure/local/README.md)).
8. **Check.**
   - `GET /v1/health` returns `{"status": "ok", "dev_login": false}`.
   - Sign-in works.
   - A viewer gets 403 on upload.
   - A known FASTA file reaches 待审核.

## Releases

1. **Read the release notes.** Note any new migration and its rollback plan; migrations are reviewed SQL in `database/migrations`.
2. **Back up.** Run `infrastructure/backup/backup.py backup`, then `verify`.
3. **Roll out.** Set `SEQUENCE_VAULT_VERSION` to the release's commit SHA and run `docker compose pull`, then `up -d`. The API restarts first and migrates as it starts; workers start once it is healthy, then web. Migrations are additive, so old processes keep working until they are replaced. Without migrate-on-start, run `admin migrate` once, then roll the API, workers and web.
4. **Confirm the version.** `docker compose images` lists the running tags.
5. **Smoke test.** Run the steps in "First installation", step 8.

**Rollback.** Set `SEQUENCE_VAULT_VERSION` back to the previous SHA, then `pull` and `up -d`. Down-migrations exist, but prefer leaving an additive schema in place. If data must be rolled back, restore the pre-release backup (see [backup and restore](backup-and-restore.md)), after exporting records created since the release.

**Policy, parser, prompt or model changes.** These apply to new runs only and never rewrite published records. Roll back by reverting the configuration and reprocessing affected open tasks.

## Monitoring

| Signal | Source | Alert when |
|---|---|---|
| API availability | `GET /v1/health` | Non-200 for 2 minutes |
| Job backlog | `SELECT count(*) FROM stage_job WHERE finished_at IS NULL AND available_at < now() - interval '10 minutes'` | Above 0 for 15 minutes |
| Stage failures | `file_task.failure_code`, and the 质量概览 dashboard | `scan_unavailable`, `parser_crash` or `parser_timeout` rising |
| Scanner | ClamAV health check | Unhealthy: processing stops at scanning, by design |
| Parser isolation | Worker log `parser sandbox runs without a network namespace` | Expected in containers. Then verify the worker has no egress. |

Logs are JSON. Residue runs are masked by the logging filter, and SQL parameters are hidden, so ordinary logs carry IDs, counts, durations and error codes only.

## Incidents

- **Scanner down.** Uploads are accepted but never parsed. Scan jobs retry with backoff, then the task fails with `scan_unavailable` and the file is marked `scan_failed`. Restore ClamAV, then ask the affected users to upload those files again; only clean files can be reprocessed.
- **Suspected malicious file.** The task is `FAILED/infected` and the object stays in storage for investigation. Do not download it on a workstation.
- **Proxy secret leaked.**
  1. Rotate `SEQUENCE_VAULT_PROXY_SECRET` on web and API together.
  2. Search the audit log (`audit_event`) for actions by unexpected subjects since the leak.
- **Wrong record published.** Records are never edited in place. A reviewer publishes a corrected version. Its provenance and the audit log show who approved and committed the wrong one.
- **Data loss or corruption.** Follow [backup and restore](backup-and-restore.md).
