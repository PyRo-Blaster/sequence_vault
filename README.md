# Sequence Vault

Internal protein sequence import, evidence review, and quality control platform.

## Project status

Phases P1–P7 of the [implementation plan](docs/implementation-plan.md) are implemented on the v1.0 [design specification](docs/design/Protein_Sequence_App_Design_v1.0_EN.md), which remains the source of truth:

- **Backend.** A Python backend (API and workers) on PostgreSQL and S3-compatible storage. It covers sandboxed FASTA, TXT, DOCX, CSV, XLSX and text-PDF parsing, deterministic QC, review and per-item commit.
- **Web app.** A Chinese-language React app.
- **Operations.** Legacy migration, backup and restore, and deployment images.

**Before the pilot.** These need organization decisions or production infrastructure:

- the identity provider;
- the approved model endpoint (AI assist is off by default);
- the real frozen acceptance set;
- a capacity and restore exercise on production-like hardware.

Runbooks: [docs/operations](docs/operations/README.md).

## Repository layout

```text
sequence_vault/
├── apps/web/                     # TypeScript UI: upload, review, records, administration
├── services/backend/             # One Python backend package; API and worker entry points
│   └── src/sequence_vault/
│       ├── domain/               # Entities, invariants, task and candidate lifecycles
│       ├── application/          # Upload, orchestration, review, commit, search use cases
│       ├── api/                  # HTTP routes, authentication context, error translation
│       ├── workers/              # Stage handlers, leases, heartbeats, retries
│       └── adapters/             # Parsers, model gateway, database, storage, queue, security
├── packages/contracts/           # Versioned JSON Schemas, examples, API catalog
├── config/                       # Processing policy and QC rule registry
├── prompts/                      # Versioned span-localization prompt templates
├── database/migrations/          # Future reviewed schema migrations
├── infrastructure/               # Local services, deployment, backup/restore configuration
├── tests/                        # Unit, integration, E2E, security, and benchmark suites
├── tools/                        # Benchmark evaluation and separate legacy migration
├── scripts/                      # Repository maintenance and structural checks
└── docs/                         # Design, architecture, decisions, roadmap, operations
```

Every reserved directory has a README or Python package marker explaining its purpose. See [architecture and dependency rules](docs/architecture.md), [workflow diagrams](docs/workflow.md), the [implementation plan and stack](docs/implementation-plan.md), [development phases](docs/roadmap.md), and [contribution guidance](CONTRIBUTING.md).

## Check the repository

Requires [uv](https://docs.astral.sh/uv/) 0.8.17, plus PostgreSQL 16+ server binaries or `SEQUENCE_VAULT_TEST_DATABASE_URL` for the database suites, and Node 22 with pnpm for the web app. uv installs the Python version in `.python-version` (3.12) when it is missing.

```sh
make setup        # create .venv from uv.lock
make check        # scaffold checks, ruff, import-linter layers, mypy, unit tests
make integration  # PostgreSQL integration, security, legacy migration and restore drill
make performance  # capacity budgets (search p95, processing p95)
make web          # web lint, typecheck, unit tests and build
make e2e          # Playwright journeys against the real backend
make dev          # local backend with a throwaway database; then `pnpm dev` in apps/web
```

CI runs all of these, and also builds and smoke-tests the container images.

## Design constraints

- Keep source files and DocumentIR evidence immutable; AI returns evidence locations and has no published-database access.
- Reconstruct and validate sequences deterministically. Do not fill missing residues or translate nucleic acids.
- Require human approval for every first-release extraction; automatic acceptance stays in shadow mode.
- Bind edits, issue resolutions, approvals, and commits to candidate revisions. Commit each batch item atomically and enforce permissions again inside the transaction.
- Preserve partial results, complete provenance, and original legacy identifiers. Keep research content and credentials out of Git and ordinary logs.

Configuration defaults are in [the processing policy](config/processing-policy.v1.json). They are proposed design budgets, not measured capacity. Copy `.env.example` to a local `.env` only once implementing the runtime; the sample is a naming contract, not a working deployment.
