# P7 Hardening and Pilot Implementation Plan

> **For agentic workers:** Use anthropic-skills:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the system safe to pilot: security and isolation tests, log redaction, project administration and a quality dashboard, the legacy migration workflow, backup and restore with a drill, capacity measurements, and deployable images.

## Tasks

- [x] **Task 1: Security.** `tests/security`: unauthorized reads, exports and commits across tenants and projects; hostile archives and XML; the parser sandbox has no credentials and cannot write files; uploaded names cannot become paths. Logging filter that masks residue runs so sequences never reach ordinary logs.
- [x] **Task 2: Administration.** Project administrators list, grant and revoke roles (`/v1/projects/{id}/members`), audited; a quality summary per project (`/v1/projects/{id}/quality`): task outcomes, failure codes, candidate outcomes, manual revision and name-change rates, commit outcomes. Web page for both.
- [x] **Task 3: Legacy migration.** `tools/legacy_migration`: read a legacy export, run the same QC, keep legacy IDs and the batch in `legacy_record` (migration 0003), commit clean records under an operator account, route anomalies to review, and write a reconciliation report (counts, unique sequences, hashes, rejected, pending).
- [x] **Task 4: Backup and restore.** `infrastructure/backup` scripts for PostgreSQL and object storage; an integration test that restores a dump into a fresh database and checks counts, hashes and project permissions.
- [x] **Task 5: Capacity.** `tests/performance`: search p95 with 100,000 record versions; processing time for a 1 MB, 100-record text file. Results are recorded, not assumed.
- [x] **Task 6: Deployment.** Dockerfiles for the backend (API, worker) and web, Docker Compose for local services (PostgreSQL, MinIO, ClamAV, oauth2-proxy), and operations runbooks.
