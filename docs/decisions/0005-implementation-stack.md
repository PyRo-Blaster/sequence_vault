# ADR 0005: Implementation stack

Status: proposed; accept or amend before P2 starts. Basis: design v1.0 section 3 ("does not mandate a particular framework or model provider"), ADRs 0001 and 0003. Details and rationale are in the [implementation plan](../implementation-plan.md).

Decisions:

- **Python tooling:** a uv workspace with one lockfile; ruff, mypy in strict mode, pytest with Hypothesis, and import-linter layer contracts in `make check`.
- **API and data:** FastAPI with synchronous endpoints and Pydantic models; SQLAlchemy 2.0 Core with psycopg 3; Alembic migrations; PostgreSQL 17.
- **Jobs:** a PostgreSQL job table with leases, fed by a transactional outbox; an existing queue is optional behind a relay.
- **Storage and scanning:** S3-compatible storage through boto3; ClamAV `clamd`; libmagic plus structural checks.
- **Parsers:** in-house FASTA and TXT readers; `lxml` for DOCX; `openpyxl` and `csv` for spreadsheets; `pdfplumber` for text PDFs; `charset-normalizer` for decoding.
- **Model gateway:** a provider-neutral port. The reference adapter uses the Anthropic Python SDK and Claude Opus 5.5 with structured outputs, on whichever Claude platform the organization approves.
- **Web:** React, TypeScript and Vite; Ant Design (`zh_CN`); TanStack Query; types generated from OpenAPI and the contract schemas; Vitest and Playwright; pnpm.

Rejected alternatives:

- Async SQLAlchemy throughout: more complexity than the specified load needs.
- Biopython for FASTA: it rewrites records and loses exact offsets.
- `python-docx`: it hides tracked changes and text boxes.
- PyMuPDF: AGPL license.
- Next.js: server rendering is not needed for an internal app.
- An OpenAI-compatible shim as the reference adapter: the gateway port already isolates the provider.

Consequences: the domain core (P1) lands first with no infrastructure. Framework choices can still change in P2–P5 without touching it, because import-linter keeps frameworks out of `domain`.
