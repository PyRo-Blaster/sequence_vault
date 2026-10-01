# P3 Ingestion Pipeline Implementation Plan

> **For agentic workers:** Use anthropic-skills:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Take an uploaded file from bytes to review-ready candidates: upload session, isolated storage, malware scan, content-based type detection, sandboxed FASTA/TXT parsing into DocumentIR, rule-based extraction, QC, and a PostgreSQL job table with leases, retries and cancellation.

**Architecture:** Use cases in `application/uploads.py` and `application/processing.py` depend on ports for object storage, scanning, type detection and parsing. Heavy work (scan, parse) runs outside database transactions; each stage then persists its result and enqueues the next stage in one short transaction that re-reads the task with `FOR UPDATE`, so duplicate or late deliveries become no-ops and cancelled tasks never advance. Parsers run in a subprocess with resource limits and an empty environment (`entrypoints/parser_main.py`).

**Tech Stack:** boto3 (S3), ClamAV INSTREAM protocol, charset-normalizer, jsonschema (runtime validation of DocumentIR), moto for S3 tests.

## Tasks

- [ ] **Task 1: Settings and contract loading.** `sequence_vault/settings.py` reads `SEQUENCE_VAULT_*` variables; `adapters/contracts.py` loads schemas and the QC registry from the repository (overridable paths) and validates documents.
- [ ] **Task 2: Object storage.** Port `ObjectStore`; `adapters/storage/local.py` (development, tests) and `adapters/storage/s3.py` (boto3, presigned links ≤ 300 s). Tests: round trip; generated keys never contain the filename; S3 via moto.
- [ ] **Task 3: Scanning.** Port `Scanner`; `adapters/security/clamd.py` (INSTREAM, chunked, size-limited) and a development scanner that is refused outside `SEQUENCE_VAULT_ENV=development`. Tests against a fake clamd server: clean, infected, unreachable (fails closed).
- [ ] **Task 4: Type detection and decoding.** `adapters/security/filetype.py` detects FASTA, text, CSV, OOXML (DOCX/XLSX), PDF; rejects OLE (DOC/XLS), macro-enabled OOXML, other archives, binaries and zip bombs regardless of extension. `adapters/parsers/decoding.py`: UTF-8, UTF-8 with BOM, then GB18030 via charset-normalizer. Tests: misleading extensions (T15), GBK text, BOM.
- [ ] **Task 5: FASTA and TXT parsers.** `adapters/parsers/fasta.py`, `adapters/parsers/text.py`, `adapters/parsers/registry.py`. Output validates against `document-ir.schema.json`; locations carry line numbers; offsets are code points.
- [ ] **Task 6: Parser sandbox.** `entrypoints/parser_main.py` and `adapters/parsers/sandbox.py`: subprocess, rlimits (address space, CPU, file size), timeout, empty environment, bounded output. Tests: parses a file; a parser crash and a timeout become `ParseFailed`.
- [ ] **Task 7: Rule extraction.** `application/rule_extraction.py`: FASTA records and sequence-like text paragraphs become extraction records; a single sequence with no in-document name uses the filename stem (`source=filename`, T01); several unnamed sequences get no name (QC07). Unit tests.
- [ ] **Task 8: Job table.** `adapters/persistence/jobs.py`: enqueue, claim with `FOR UPDATE SKIP LOCKED` and a lease, heartbeat, finish, retry with exponential backoff and jitter, give up after three transient failures. Integration tests: two workers never hold the same job; an expired lease is reclaimed.
- [ ] **Task 9: Upload and processing use cases.** Upload session, content upload with size limit, completion that verifies byte count and SHA-256 and enqueues scanning idempotently; stage handlers for scan, parse, extract, validate; cancellation; reprocessing creates a new run and supersedes open candidates (T16). Domain: `FileTask.reprocess()`.
- [ ] **Task 10: Worker.** `workers/worker.py` loop and `entrypoints/worker_main.py`. Integration tests: T01, T02, T09, T15, T16, T20, duplicate delivery, transient scanner failure retried then failed closed.

## Done when

`make check` and `make integration` pass, and an uploaded multi-record FASTA reaches `REVIEW_READY` with one candidate per record.
