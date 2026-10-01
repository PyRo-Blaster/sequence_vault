# Sequence Vault

Internal protein sequence import, evidence review, and quality control platform.

## Project status

This repository is an architecture scaffold based on the [v1.0 design specification](docs/design/Protein_Sequence_App_Design_v1.0_EN.md). Product features, database migrations, runtime integrations, and benchmark targets are not implemented or verified yet. The specification is the source of truth; the folders below provide implementation boundaries.

Baseline: a Chinese-language TypeScript web interface, a modular Python backend with separate processing workers, PostgreSQL, and S3-compatible object storage. Frameworks, enterprise authentication, queue infrastructure, and approved model providers remain explicit implementation decisions.

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

Requires [uv](https://docs.astral.sh/uv/) 0.8.17. uv installs the Python version in `.python-version` (3.12) when it is missing.

```sh
make setup   # create .venv from uv.lock
make check   # scaffold checks, lint, import contracts, types and unit tests
```

`make check` validates the synthetic examples against the draft JSON Schemas, checks that the schemas reject states the design forbids, runs ruff, mypy and the import-linter layer contracts, and runs the backend unit tests. CI runs the same commands. Backend unit tests live in `tests/unit`; no application server exists yet.

## Design constraints

- Keep source files and DocumentIR evidence immutable; AI returns evidence locations and has no published-database access.
- Reconstruct and validate sequences deterministically. Do not fill missing residues or translate nucleic acids.
- Require human approval for every first-release extraction; automatic acceptance stays in shadow mode.
- Bind edits, issue resolutions, approvals, and commits to candidate revisions. Commit each batch item atomically and enforce permissions again inside the transaction.
- Preserve partial results, complete provenance, and original legacy identifiers. Keep research content and credentials out of Git and ordinary logs.

Configuration defaults are in [the processing policy](config/processing-policy.v1.json). They are proposed design budgets, not measured capacity. Copy `.env.example` to a local `.env` only once implementing the runtime; the sample is a naming contract, not a working deployment.
