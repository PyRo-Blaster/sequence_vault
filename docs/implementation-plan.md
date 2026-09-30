# Implementation plan

Status: proposed. Basis: the [design specification](design/Protein_Sequence_App_Design_v1.0_EN.md), [architecture](architecture.md), [workflow diagrams](workflow.md) and ADRs 0001–0004. Stack choices are recorded in [ADR 0005](decisions/0005-implementation-stack.md).

The work is split into seven sub-plans. Each one produces working, tested software on its own and is detailed as a task-by-task plan when it starts. The first, the domain core, is already detailed in [plans/2026-09-30-domain-core.md](superpowers/plans/2026-09-30-domain-core.md).

## 1. Technology stack

### Backend (Python)

| Area | Choice | Why |
| --- | --- | --- |
| Runtime and packaging | Python 3.12; uv workspace with one `uv.lock` | Fast, reproducible installs; one lockfile for the backend and the Python tools |
| Quality tooling | ruff, mypy (strict), pytest, Hypothesis, import-linter | Hypothesis suits span and normalization invariants; import-linter enforces the layer rules in `architecture.md` |
| HTTP API | FastAPI with synchronous endpoints, Pydantic v2 request/response models, Uvicorn | Generates the OpenAPI definition the spec lists as a deliverable. Synchronous code keeps one code path for the API and workers at 100 users |
| Database | PostgreSQL 17; SQLAlchemy 2.0 Core with psycopg 3; Alembic migrations | Explicit transactions, `SELECT … FOR UPDATE`, `SKIP LOCKED` and constraint handling, without ORM identity-map surprises inside the commit transaction |
| Task queue | PostgreSQL job table with leases and heartbeats, fed by a transactional outbox | Idempotent enqueue in the same transaction as the task row (ADR 0003). A relay can publish to an existing queue if the team has one |
| Object storage | S3-compatible (MinIO locally) through boto3 | Generated object keys; presigned download links of at most five minutes after re-authorization |
| Malware scanning | ClamAV `clamd` over the INSTREAM protocol | Fails closed: an unavailable scanner fails the task |
| File-type detection | libmagic (`python-magic`) plus structural checks | Rejects macro parts in OOXML, enforces decompression ratio and size limits, never trusts extensions |
| FASTA and TXT | In-house reader | Needs exact code-point offsets and line numbers; Biopython rewrites records |
| Text decoding | UTF-8 and UTF-8 with BOM, then `charset-normalizer` (including GB18030) | Chinese Windows files are often GBK; the chosen encoding is stored in DocumentIR |
| DOCX | `lxml` over the OOXML parts, with entity resolution and network access disabled | `python-docx` hides tracked changes, text boxes, hidden text and comments, which the spec requires to be reported |
| XLSX and CSV | `openpyxl` (formulas never evaluated; cached values read separately) and the `csv` module | Reports formula cells, hidden rows, hidden columns and hidden sheets |
| Text PDF | `pdfplumber` | Page-level text with coordinates under the MIT license. PyMuPDF is avoided because of AGPL terms |
| Parser isolation | Subprocess with resource limits and an empty environment first; `nsjail`, `bubblewrap` or a no-egress container before the pilot | ADR 0003: parsers never hold credentials |
| Model gateway | Provider-neutral port. The reference adapter uses the Anthropic Python SDK with Claude Opus 5.5 (`claude-opus-5-5`) and structured outputs (`output_config.format`) | Returns spans only. Reachable through the Claude API, Amazon Bedrock, Google Vertex AI or Microsoft Foundry, whichever the organization approves for region and retention. Disabled until approved |
| Authentication | OIDC authorization-code flow at the API (Authlib), HttpOnly session cookie and CSRF token | No tokens in browser storage. The identity provider is still open |
| Observability | structlog JSON logs with a redaction filter; OpenTelemetry traces and metrics | Ordinary telemetry carries only IDs, counts, durations and error codes |
| Integration tests | testcontainers for PostgreSQL and MinIO | Real constraints and transactions instead of mocks |

Structured outputs accept only part of JSON Schema: no `oneOf`, `if`/`then`/`else`, `minimum` or `minLength`. The gateway therefore sends a flattened, model-facing copy of `extraction-result.schema.json`, then validates the reply against the full schema and the domain's `check_extraction`. A `refusal` or `max_tokens` stop reason counts as invalid output: one repair attempt, then human handling.

### Frontend (TypeScript)

| Area | Choice | Why |
| --- | --- | --- |
| Build and packages | React, TypeScript and Vite; pnpm with a committed lockfile | An internal single-page app needs no server rendering |
| UI components | Ant Design with the `zh_CN` locale | Mature Chinese-first tables, forms, uploads and date handling |
| Data and routing | TanStack Query and React Router | Job polling, cache invalidation after edits, explicit handling of 409 conflicts |
| API types | `openapi-typescript` and `openapi-fetch` from the backend OpenAPI; `json-schema-to-typescript` for contract types | One source of truth; no hand-copied types |
| Evidence display | DocumentIR blocks as text; `pdfjs-dist` for PDF pages with highlighted regions; `diff` for character-level sequence diffs | The review workspace shows the source beside the candidate |
| Tests and linting | Vitest and Testing Library; Playwright for end-to-end tests; ESLint (typescript-eslint) and Prettier | Playwright also drives the T01–T20 journeys |

Code-point offsets are converted to UTF-16 indices in one tested function in `apps/web/src/lib`.

### Infrastructure

| Area | Choice |
| --- | --- |
| Images | Multi-stage Docker images pinned by digest: `api`, `worker` and `parser-sandbox` from the same backend package |
| Local services | Docker Compose with PostgreSQL 17, MinIO and ClamAV, bound to loopback |
| Deployment | Decided with the infrastructure team (Kubernetes or VMs). The parser sandbox gets no network egress and no secrets |
| Backup | PostgreSQL WAL archiving (for example pgBackRest) and object-store versioning, with a restore drill against the 24-hour RPO and 8-hour RTO |

## 2. Repository and package layout

```text
sequence_vault/
├── pyproject.toml, uv.lock, .python-version     # uv workspace root and shared tooling
├── services/backend/
│   ├── pyproject.toml                           # package: sequence-vault
│   └── src/sequence_vault/
│       ├── domain/                              # pure Python, no frameworks (P1)
│       │   ├── spans.py                         # code-point spans, reconstruction, evidence mapping
│       │   ├── normalization.py                 # QC02 whitespace/case with transformation log
│       │   ├── qc/registry.py                   # rules, severities, allowed resolutions
│       │   ├── qc/characters.py                 # QC03–QC06 character classes
│       │   ├── qc/engine.py                     # evaluation, context rules, molecule type
│       │   ├── extraction.py                    # extracted records and cross-field checks
│       │   ├── candidate.py                     # revisions, resolutions, approval, commit guard
│       │   ├── task.py                          # file task lifecycle
│       │   ├── naming.py                        # name_key
│       │   └── publication.py                   # dedup and version decisions (QC09, QC10)
│       ├── application/                         # use cases and ports (P1–P4)
│       │   ├── ports.py                         # repositories, storage, scanner, queue, parser, model gateway, clock
│       │   ├── contract_mapping.py              # JSON contracts <-> domain
│       │   ├── authorization.py                 # project roles; rechecked inside transactions
│       │   ├── uploads.py, processing.py        # upload sessions; stage handlers
│       │   ├── review.py, commit.py             # edits, resolutions, approvals; per-item commits
│       │   └── records.py                       # search, history, FASTA export
│       ├── adapters/
│       │   ├── persistence/                     # SQLAlchemy tables, repositories, unit of work, job table, outbox
│       │   ├── storage/                         # S3 client, presigned links
│       │   ├── security/                        # clamd client, type detection, archive limits
│       │   ├── parsers/                         # registry, fasta, text, docx, xlsx, csv, pdf, sandbox launcher
│       │   ├── ai/                              # model gateway, prompt loader, output validation
│       │   └── auth/                            # OIDC and sessions
│       ├── api/                                 # FastAPI app factory, routers, error contract
│       ├── workers/                             # worker loop, leases, heartbeats, cancellation
│       └── entrypoints/                         # api_main, worker_main, parser_main (sandbox)
├── database/migrations/                         # Alembic
├── apps/web/src/{features,components,lib}       # React app
├── tools/evaluation/, tools/legacy_migration/   # workspace members, depend on sequence-vault
└── tests/{unit,integration,security,e2e,benchmarks}
```

Dependency direction is enforced by import-linter in `make check`: `api | workers` → `adapters` → `application` → `domain`, and the domain may not import frameworks or provider SDKs.

## 3. Delivery sequence

| Plan | Scope | Phase | Depends on | Acceptance cases and exit check |
| --- | --- | --- | --- | --- |
| P1 Domain core | Toolchain, spans, normalization, QC engine, lifecycles, publication decisions, contract mapping | B | — | Unit and property tests; the synthetic example round-trips exactly. **Detailed plan written** |
| P2 Persistence and commit | Alembic schema, repositories, unit of work, commit transaction, idempotency keys, dedup and versions | B | P1 | Integration tests for T10, T11, T12, T13, T18: no duplicate versions, stale approvals and revoked permissions fail |
| P3 Ingestion pipeline | Upload sessions, object storage, scanner, job table and outbox, worker loop, sandboxed FASTA/TXT parser | B | P1, P2 | T01, T02, T15, T20: worker restarts resume; cancelled tasks cannot commit |
| P4 API and sign-in | `/v1` routes from the API catalog, error format, OIDC sessions, OpenAPI | B | P2, P3 | Contract tests per route, including 403, 409, 413 and 422 |
| P5 Web app | Upload and task list, review workspace, records, search and export | B | P4 | Playwright E2E for single and multiple FASTA; published record equals the gold file exactly |
| P6 Intelligent extraction | DOCX, CSV, XLSX and PDF parsers; model gateway; prompt v1; evaluation tool | C | P3, P5 | T03–T09, T14, T16, T17, T19; frozen-set metrics: whole-sequence accuracy ≥ 99%, recall ≥ 98%, name association ≥ 98% |
| P7 Hardening and pilot | Security, load and recovery tests; deployment; backups; legacy migration | D | P1–P6 | All T01–T20, capacity budgets, recovery drill, migration reconciliation, pilot sign-off |

The Phase B exit gate (FASTA end to end) is P1–P5. P2 and P3 can run in parallel once P1 lands.

## 4. Decisions needed

| Decision | Owner | Needed before |
| --- | --- | --- |
| Accept ADR 0002 contracts and ADR 0003 isolation and outbox | Tech lead | P2 |
| Existing queue to relay to, or the PostgreSQL job table alone | Infrastructure | P3 |
| Enterprise identity provider and OIDC details | IT and security | P4 |
| Deployment target and sandbox runtime | Infrastructure | P7 (sandbox level 1 is enough for P3) |
| Approved model platform, region, retention and training terms | Security and legal | P6. Deterministic parsing works without it |
| ADR 0004 normalization questions and extended-residue policy | Research data owner | P6 benchmark freeze |
| Text PDF in release one; retention periods; user scale | Data owner | P6 and P7 |

## 5. Main risks

- **Parser coverage for DOCX and PDF edge cases.** Mitigation: coverage warnings raise QC08 on every candidate in the file, and the frozen set is split by template family.
- **Model reply drift or refusals.** Mitigation: spans are checked against the stored document, the reply is validated against the full schema, one repair attempt is allowed, and the fallback is human handling. Model confidence is never used.
- **Commit concurrency bugs.** Mitigation: database constraints alongside transaction checks, and P2 integration tests with concurrent sessions.
- **Scope creep in the review UI.** Mitigation: P5 ships the minimum from spec section 7; split, join and fragment registration come in P6.
