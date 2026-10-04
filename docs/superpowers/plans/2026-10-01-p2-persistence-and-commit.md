# P2 Persistence and Commit Implementation Plan

> **For agentic workers:** Use anthropic-skills:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Store tenants, projects, files, runs, immutable blocks, candidates, published records and audit events in PostgreSQL, and implement the per-item commit transaction with idempotency, deduplication and versioning.

**Architecture:** Alembic migration for the whole schema; SQLAlchemy 2.0 Core tables in `adapters/persistence`; ports in `application/ports.py`; the commit use case in `application/commit.py` runs one transaction per candidate and re-checks everything inside it. Integration tests run against a real PostgreSQL: `SEQUENCE_VAULT_TEST_DATABASE_URL` when set (CI uses a PostgreSQL 17 service), otherwise a throwaway local cluster started with `initdb`.

**Tech Stack:** SQLAlchemy 2.0 Core, psycopg 3, Alembic, PostgreSQL 16+.

## Tasks

- [ ] **Task 1: Dependencies and test database fixture.** Add `sqlalchemy`, `psycopg[binary]`, `alembic` to `services/backend/pyproject.toml`. `tests/integration/conftest.py` provides a migrated template database and a fresh database per test (`CREATE DATABASE … TEMPLATE`). `pytest` runs `tests/unit` by default; `make integration` runs `tests/integration`.
- [ ] **Task 2: Schema.** `database/migrations/` (Alembic env + `0001_initial.py`) and `adapters/persistence/tables.py`. Constraints: `sequence_entity (tenant_id, molecule_type, sha256)` unique; `record (project_id, name_key)` unique; `record_version (record_id, version_no)` unique; one current version per record (partial unique index); `document_block` rows cannot be updated or deleted (trigger). Test: migration applies; each constraint rejects a violating insert; block update raises.
- [ ] **Task 3: Serialization.** `adapters/persistence/serialization.py` converts `Candidate` and `QcResult` to JSON and back losslessly. Unit test: round trip equals the original for clean, blocked, typed and pending candidates.
- [ ] **Task 4: Ports and repositories.** `application/ports.py` (Protocols) and `adapters/persistence/repositories.py` (`SqlUnitOfWork`). Test: save and reload a candidate; membership roles; entity lookup by hash.
- [ ] **Task 5: Authorization.** `application/authorization.py`: roles `uploader`, `reviewer`, `viewer`, `project_admin`; `require(roles, action)`. Unit tests for every action.
- [ ] **Task 6: Review use cases.** `application/review.py`: rename, revise sequence (re-runs QC), resolve, approve, reject, archive, with revision checks and audit events. Integration tests: stale revision → `RevisionConflict`; edit after approval voids it (T12).
- [ ] **Task 7: Commit use case.** `application/commit.py`: per item, in its own transaction: idempotency lookup, `SELECT … FOR UPDATE`, recheck reviewer role, file security status, task cancellation, approved revision, QC version and BLOCK issues; plan publication; create or reuse entity, create record or version, provenance, audit, mark committed, store idempotency result. Returns `COMMITTED`, `ALREADY_COMMITTED`, `CONFLICT` or `FAILED` with a reason code. Integration tests: T10 (same name/different sequence needs a decision; same sequence/different names reuse one entity), T11 (same key twice → same result, one version), T12 (stale approval), T13 (role revoked before commit), T18 (cross-project reuse does not reveal the other project), T20 (cancelled task), concurrent commits of the same name produce one record.

## Done when

`make check` and `make integration` pass; CI runs both.
