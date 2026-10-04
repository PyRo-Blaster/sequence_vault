# Database migrations

Reviewed Alembic migrations for PostgreSQL. Each version file embeds its DDL verbatim so reviewers read exactly what runs.

```sh
SEQUENCE_VAULT_DATABASE_URL=postgresql+psycopg://user@host/db \
  uv run alembic -c database/alembic.ini upgrade head
```

`services/backend/src/sequence_vault/adapters/persistence/tables.py` mirrors the schema for queries; `tests/integration/test_schema.py` fails if the two drift. The schema enforces the design's guarantees in the database as well as in code:

- `sequence_entity (tenant_id, molecule_type, sha256)`, `record (project_id, name_key)` and `record_version (record_id, version_no)` are unique, and each record has one current version.
- `document_block`, `sequence_entity` and `legacy_record` rows cannot be updated or deleted; `record_version` rows can only be superseded.

Versions: `0001` initial schema; `0002` per-task parse options; `0003` legacy migration batches and legacy IDs; `0004` search indexes; `0005` case-insensitive unique sign-in names.

**Rolling out `0005`.** Sign-in names are matched without regard to case, so `0005` adds a unique index on `lower(subject)`. If two users differ only in case, the migration stops with the list and the database stays at `0004`. Merge each pair first: move the project roles to the user to keep (`admin grant`), then delete or rename the other. Audit rows reference user IDs and stay as they are. Find pairs with:

```sql
SELECT lower(subject), array_agg(id || ' ' || subject) FROM app_user
GROUP BY lower(subject) HAVING count(*) > 1;
```

Never edit a released migration; add a new version with a rollout and rollback plan.
