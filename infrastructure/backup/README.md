# Backup and recovery

`backup.py` backs up PostgreSQL and the object store together, and proves that a restore reproduces them. It reads the same `SEQUENCE_VAULT_*` settings as the services. It needs `pg_dump` and `pg_restore` at the same major version as the server, or newer. The tool uses the newest client under `/usr/lib/postgresql`, or `SEQUENCE_VAULT_PG_BIN` when set. The database password goes through `PGPASSWORD`, never the command line.

```sh
uv run python infrastructure/backup/backup.py backup /backups          # prints the new backup directory
uv run python infrastructure/backup/backup.py verify /backups/20261001T020000Z
# Settings point at an EMPTY database and store:
uv run python infrastructure/backup/backup.py restore /backups/20261001T020000Z
uv run python infrastructure/backup/backup.py fingerprint              # current state, for comparison
```

A backup directory holds:

- `database.dump`: `pg_dump --format=custom`, taken from an exported snapshot.
- `objects/<key>`: every stored source file the snapshot references.
- `manifest.json`: the creation time, the server version, the object count and the fingerprint.
- `SHA256SUMS`: checksums of all of the above.

**Consistency.** The fingerprint is computed inside the same snapshot as the dump. It holds:

- row counts per table and the schema revision;
- hashes over entities, records, record versions and grants;
- a recomputed SHA-256 for every stored source file.

Object keys are generated and never reused, so objects copied after the snapshot cover everything it references.

**Restore.**

1. Checks `SHA256SUMS`.
2. Refuses a non-empty database.
3. Runs `pg_restore --single-transaction --exit-on-error`.
4. Copies the objects into the store.
5. Fingerprints the result and fails on any difference: counts, hashes, permissions, or a missing or altered object.

Fingerprints and manifests contain IDs, counts and hashes, never sequences. The dump and the objects do contain research data. Store them encrypted, with the same access controls as production.

The recovery drill `tests/integration/test_backup_restore.py` runs in CI. It:

- populates a database through the legacy migration;
- backs it up and restores it into a fresh database and store;
- compares fingerprints and checks that project roles survived;
- checks that a damaged backup, a non-empty target and a missing object are each refused or reported.

The schedule, retention and the RPO/RTO exercise are covered in [docs/operations/backup-and-restore.md](../../docs/operations/backup-and-restore.md).
