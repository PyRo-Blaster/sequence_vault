# Intelligent Protein Sequence Import and Quality Control Platform

## Application Technical Design and Development Acceptance Specification

**Version:** 1.0  
**Date:** September 29, 2026  
**Audience:** Product managers, developers, testers, and research data administrators

## 1. Project Objectives and Design Decisions

Rebuild the departmental protein sequence repository so that researchers can upload sequence files in common formats. The system extracts names, amino acid sequences, and source evidence, then stores the results after deterministic validation and any required human review. Development should focus on extraction accuracy, correct name-to-sequence associations, and preventing errors from entering the published repository.

Use a controlled AI workflow. AI interprets document structure and identifies evidence; software reads sequences from the specified locations and performs normalization and validation; the application backend manages permissions, versions, and transactional writes. AI has no write access to the published database.

### Key Boundaries

The first release accepts only protein sequences into the published repository. Files suspected of containing nucleic acids may retain their originals and candidate records, but the system must flag them as out of scope or ask the user to confirm the molecule type. It must not automatically translate them. A file may contain multiple sequences, each reviewed and committed independently. Files without sequence content may be archived as awaiting additional information; they must not create empty sequence entities.

All extraction results require human confirmation in the first release. The system still calculates eligibility for automatic acceptance for evaluation in shadow mode. Automatic ingestion may subsequently be enabled only for formats and rules that pass separate acceptance testing. A model's self-reported confidence must not determine acceptance.

| Design Area | First-Release Decision |
| --- | --- |
| Application form | Internal web application; asynchronous file processing; Chinese user interface |
| Storage principles | Immutable source files; separation of candidates and published records; traceable changes |
| AI boundaries | No completion of missing sequences, no replacement with sequences retrieved online, and no inferred project or version relationships |
| Legacy data | Preserve legacy IDs and original names; migrate through a separate workflow |
| Specification status | This document defines proposed product contracts and targets; performance and accuracy must be verified through testing |

### Out of Scope for the First Release

Sequence design, function prediction, structure prediction, similarity search, plasmid maps, DNA translation, multichain molecule assembly, and regulatory electronic signatures are out of scope. Antibody heavy and light chains may be stored as separate protein records and grouped using relationship tags; they must not be concatenated into a single sequence without an explicit basis.

## 2. Functional Scope and User Workflow

| Input | First-Release Handling | Limitations and Future Extensions |
| --- | --- | --- |
| FASTA, TXT | Standard parsing or extraction from text blocks | Support multiple records; preserve original headers |
| DOCX | Paragraphs and tables; filename as a candidate name | Explicitly flag images, text boxes, tracked changes, and hidden content |
| CSV, XLSX | Identify names and sequences using headers and row/column relationships | Preserve worksheet names and cell addresses; do not execute formulas |
| Text-based PDF | Extract text by page and coordinates | Route uncertain reading order or mixed scanned pages to human review |
| PNG, JPEG, scanned PDF | Phase 2: OCR and visual localization | Highlight uncertain characters; always require human review |
| Other files | Explicitly reject or archive only | Do not parse DOC, XLS, macro-enabled files, or archives in the first release |

Multiformat support expands through a parser registry; it does not promise successful extraction from every possible file. Do not identify formats solely by extension. The upload page must display supported formats and limits before upload.

### Primary User Journey

The user selects an authorized project, drops in files, and monitors security checks and extraction progress. Once processing finishes, the user opens the review page and checks each name, sequence, and evidence reference. Edits trigger revalidation. The user may commit passing items while leaving others pending additional content or rejecting them. The task list must clearly distinguish committed and unresolved counts; partial success must not be displayed as complete success.

### Screens

| Screen | Key Content |
| --- | --- |
| Upload and task list | Project, file, status, progress, candidate count, failure reason, retry |
| Extraction review | Source evidence beside candidates; issue localization; editing, splitting, and reassociation |
| Sequence search | Name, alias, project, length, uploader, date; exact sequence lookup |
| Record details | Sequence, version, provenance, reviewer, change history, and FASTA export |
| Administration and quality dashboard | Member permissions, processing policies, versions, failure rates, and manual correction rates |

### Roles and Permissions

Uploaders may work on drafts in authorized projects. Reviewers may confirm and publish records. Viewers may search and export only authorized data. Project administrators manage members and application records. The first release may allow an uploader to also act as reviewer, but the identity must be recorded. Platform operations roles do not receive access to research data by default.

## 3. System Architecture and Task Orchestration

Use a modular backend with separate processing workers rather than splitting the first release into many microservices. The browser uploads files and performs review through application APIs. The API places files in isolated storage and creates tasks. Workers perform scanning, parsing, AI extraction, and quality control. The commit service writes approved candidates to the published repository.

| Module | Input and Output Contract |
| --- | --- |
| Upload and isolated storage | File bytes → `file_id`, SHA-256, detected MIME type, security status |
| Document parser | Source file → immutable `DocumentIR`, evidence locations, coverage warnings |
| Extraction orchestrator | `DocumentIR` → candidate names, sequence span references, ambiguities |
| Normalization and QC | Candidate references → deterministically reconstructed sequence, transformation log, rule results |
| Review and commit service | Candidate revision and user decision → published version or conflict response |
| Storage layer | Object storage for source files and evidence; relational database for structured application data |

### Implementation Baseline

The proposed baseline is a TypeScript web frontend, Python API and processing workers, PostgreSQL, and S3-compatible object storage. Use the team's existing reliable task infrastructure for queuing. The first release does not mandate a particular framework or model provider. Route model access through a server-side gateway and pin the model, prompt template, and output schema versions. Lock dependency versions during implementation and complete compatibility testing.

### Task States

File tasks follow:

`UPLOADED → SCANNING → PARSING → EXTRACTING → VALIDATING → REVIEW_READY → COMPLETED`

Any stage may enter `FAILED` or `CANCELLED`; unsupported formats enter `UNSUPPORTED`. `COMPLETED` means every candidate has been committed, rejected, or explicitly archived. Keep the task in `REVIEW_READY` while items remain pending additional content.

Candidate items progress from `DRAFT` to `NEEDS_REVIEW` or `BLOCKED`, and then, once issues are resolved and approval is granted, to `APPROVED` and `COMMITTED`. They may also enter `REJECTED` or `PENDING_CONTENT`. Editing a candidate invalidates its approval and returns it to the review state determined by revalidation. Files that fail security checks cannot produce candidates eligible for commitment.

### Recovery and Retries

Persist input/output summaries and versions at each stage. Retry transient network failures using exponential backoff with jitter, with a proposed maximum of three retries. Do not repeatedly retry deterministic parsing failures. Workers use task leases and heartbeats; duplicate delivery must be idempotent. The commit service rejects late results after cancellation. Re-extraction creates a new `extraction_run`, preserves earlier results, and does not overwrite approved versions.

## 4. Extraction Protocol and Evidence Model

### Unified Document Representation: DocumentIR

Parsers produce blocks in reading order. Each block has a stable ID, type, raw text, location, and extraction method. DOCX locations use paragraph indices or table row/column coordinates; XLSX uses worksheet names and cell addresses; PDF uses page numbers and coordinates. Locations are bound to the source file hash and parser version rather than temporary page numbers produced by later rendering.

Text offsets use Unicode code points and half-open intervals: the start is inclusive and the end is exclusive. The API explicitly declares `offset_unit=unicode_codepoint`; the frontend must not interpret these offsets directly as JavaScript UTF-16 indices. Image evidence retains crop coordinates, image hashes, and OCR versions.

### Two-Step Extraction

Rules first identify FASTA records, continuous residue text, and candidate table regions. AI then determines how names relate to candidate spans. AI returns `block_id`, start/end offsets, and assembly order. Software retrieves characters from the immutable IR and assembles the sequence. For text-based extraction, a free-text sequence generated by the model is not authoritative.

Chunking follows table rows, headings, and record boundaries; it must not arbitrarily split a sequence by token count. For very long sequences, provide only locations, context, and summaries to the model; software handles the sequence body. Joining spans across blocks requires evidence of structural continuity. Deduplicate overlapping windows by evidence location, not content alone.

### Example Extraction Result

```json
{
  "schema_version": "1.0",
  "file_id": "file_demo",
  "run_id": "run_demo",
  "records": [
    {
      "candidate_id": "candidate_demo",
      "name": {
        "value": "RSPO3_C07_v2",
        "source": "filename",
        "evidence": "filename_stem"
      },
      "molecule_type": "protein",
      "sequence_spans": [
        {
          "block_id": "p2",
          "start": 0,
          "end": 24,
          "order": 1
        }
      ],
      "association_status": "unambiguous",
      "issues": []
    }
  ],
  "coverage": {
    "unresolved_blocks": [],
    "truncated": false
  }
}
```

This example illustrates the field contract and contains no actual experimental sequence. The output validator checks required fields, types, reference existence, valid ranges, and unknown fields. Allow at most one controlled repair attempt for invalid output, then route unresolved failures to human review. Any unexplained block suspected of containing sequence content must be included in `unresolved_blocks` to prevent missed extraction.

## 5. Name Association and Complex File Handling

### Name Selection Rules

Prefer a FASTA header directly paired with the sequence or a name in the same table row, followed by an explicit local heading. Use the filename as a fallback only when there is a single sequence and no conflict. Preserve both the original and display names. Removing a filename extension can be deterministic; project, construct, and version fields must come from explicit fields or user confirmation.

| Scenario | Expected Behavior |
| --- | --- |
| Filename contains the name; body contains one sequence | Extract the filename stem, mark evidence as `filename`, and request confirmation |
| Filename conflicts with a name in the body | Preserve both candidates, raise `NAME_CONFLICT`, and prohibit automatic acceptance |
| Filename contains a name; body contains multiple sequences | Create separate candidates; do not replicate the same name as though each mapping were confirmed |
| Multicolumn tables or merged cells | Parse row/column relationships; require manual association when pairing is not unique |
| Antibody heavy and light chains | Extract separately and retain chain labels; do not concatenate different chains |
| Same sequence appears multiple times | Preserve evidence from each occurrence; distinguish repeated presentation from separate application records |
| Body contains only a name and no sequence | Set `PENDING_CONTENT`; do not retrieve a substitute online or create a sequence entity |
| Ellipses or missing regions | Block commitment as a complete extraction; allow explicit registration of evidence-supported fragments |

### DOCX Coverage and Tracked Changes

Parse body text and tables, and detect headers, footers, text boxes, images, hidden text, comments, tracked changes, and embedded objects. Content not fully supported in the first release must generate coverage warnings. If tracked changes exist, the user selects either the original view or the view with changes accepted; the system records that choice and reparses the document. Insertions and deletions must not be silently ignored.

### Spreadsheets and PDF

Do not execute XLSX macros or formulas. Formula cells require source labeling and review even when cached values are available. Report the number of hidden rows, columns, and worksheets and whether they were parsed. Check PDF text coverage page by page. Scanned pages, uncertain two-column reading order, hyphenation, and headers mixed into sequence text require human review.

### OCR Path

OCR retains character-level or word-level coordinates. Users verify ambiguous characters such as `I/L` or `O/0` against the image. Agreement between two recognizers does not prove correctness. OCR results introduced in subsequent extensions must not be automatically ingested. If a residue cannot be read, keep the issue unresolved rather than guessing.

## 6. Sequence Normalization and Quality Control Rules

Normalization preserves `raw_text`, `normalized_sequence`, and `transformation_log`. The standard protein alphabet is `ACDEFGHIKLMNPQRSTVWY`. Treat `B`, `Z`, `J`, `X`, `U`, and `O` as extended characters: retain the original value, flag its meaning for confirmation, and prohibit automatic substitution. A sequence containing only characters such as `ACGT` cannot be classified as protein based on its alphabet alone.

| Rule | Default Severity | Handling |
| --- | --- | --- |
| QC01: Empty sequence or out-of-range reference | `BLOCK` | Prevent commitment; repair references or await additional content |
| QC02: Whitespace, line breaks, and letter case | `INFO` | Permit automatic normalization and log transformations |
| QC03: Digits, invalid symbols, or Unicode look-alike characters | `BLOCK` | Locate the characters; do not delete indiscriminately |
| QC04: B, Z, J, X, U, O | `REVIEW` | Confirm residue semantics; allow storage of original values after confirmation |
| QC05: Ellipses, truncated output, or omitted blocks | `BLOCK` | Re-extract or obtain additional material; do not assume completeness |
| QC06: Asterisks, gaps, or numbering | `REVIEW` | Select an explicit source-based transformation; log the rule and positions |
| QC07: Name conflict or unclear mapping | `REVIEW` | User selects a name, or splits and reassociates candidates |
| QC08: OCR, tracked changes, or unsupported content | `REVIEW` | Check the source and resolve coverage risks |
| QC09: Same name with a different sequence | `REVIEW` | Explicitly create a new version or record, or cancel; prohibit overwriting |
| QC10: An identical sequence already exists | `INFO` | Reuse the sequence entity; decide separately how to handle the application record |
| QC11: Uncertain protein classification | `REVIEW` | Confirm molecule type; nucleic acids cannot enter the first-release published repository |

### Rule Execution Details

Digits may be removed under a dedicated rule only when the parser confirms they are residue-position numbers and that the numbering is sequential and consistent. This is not a general cleanup operation. A terminal `*` may be removed after user confirmation with an audit trail; the meaning of an internal `*` must be resolved. Alignment gaps must not be removed by default. A user clicking Approve does not turn an unreadable residue into a known residue.

There is no generic Ignore button for `BLOCK` issues. Resolve them by correcting the input, providing additional source material, or explicitly registering a fragment. A fragment must preserve the continuous sequence actually visible in the source and set `completeness=fragment`; missing regions must not be filled in. Manual sequence edits require a reason, character-level differences, and an `origin` value indicating manual revision.

### Future Eligibility for Automatic Acceptance

All of the following must hold: reliable text-based parsing, complete coverage, unique name mapping, no `BLOCK` or `REVIEW` issues, consistent reconstruction from the source, no duplicate-related conflicts, and parser/policy versions that have passed benchmark testing. Human confirmation remains mandatory in the first release. Increasing model confidence cannot bypass any condition.

## 7. Human Review and Commit Behavior

### Review Workspace

Display the source text or page image on the left, and the candidate name, type, length, completeness, sequence, and issues on the right. Clicking a name or residue range locates the evidence. Display sequences in fixed-width columns with residue positions. Users should be able to read, correct, and commit on one screen without comparing multiple downloaded files.

| Interaction | Contract |
| --- | --- |
| Edit name | Show extracted and current values; retain filename provenance |
| Edit sequence | Character-level diff; mandatory reason; rerun QC after saving |
| Split or join | Explicit evidence ranges; show order and boundaries before joining |
| Resolve issues | Record a resolution for each issue, bound to the candidate `revision` |
| Bulk approve | Apply only to selected items without blocking issues and with unchanged revisions; show the count |
| Commit | Preview counts for new records, reuse, and new versions; return per-item results |
| Concurrent editing | Return `409` for revision conflicts; prompt refresh and comparison; prohibit overwriting |

### Duplicate and Version Decisions

Within a project, create `name_key` by trimming leading/trailing whitespace and applying case folding; retain original capitalization for display. For the same name and sequence, additional provenance may be attached. For the same name with a different sequence, the user must select a new version or rename the record. Different names with the same sequence may create separate application records that reuse one sequence entity. Do not infer a parent version automatically from `v2` in a filename.

### Commit Transaction

Within a transaction, the commit service rechecks user permissions, file security status, candidate `revision`, approval records, and QC policy version. It finds or creates the sequence entity, creates the application record version and provenance links, appends an audit event, and marks the candidate as committed. On error, roll back the entire item.

A batch request commits each candidate atomically and returns `COMMITTED`, `ALREADY_COMMITTED`, `CONFLICT`, or `FAILED` per item. The interface explicitly shows partial success. The server binds each item's idempotency key to its candidate ID and approved revision; retries return the same result. A new extraction run cannot reuse an earlier approval.

### Traceability in the Published Repository

Record details expose the source file, extraction evidence, normalization steps, manual changes, approver, and timestamp. Published sequence content cannot be edited in place; changes create a new version. Earlier versions may be marked as superseded. Search displays current versions by default and allows authorized users to view history.

## 8. Data Model and API Contracts

| Entity | Main Fields and Constraints |
| --- | --- |
| `source_file` | `id`, `tenant_id`, `project_id`, `original_name`, `sha256`, `object_key`, `security_status` |
| `extraction_run` | `file_id`, `parser_version`, `model_version`, `prompt_version`, `schema_version`, `qc_version`, `status` |
| `document_block` | `run_id`, `block_id`, `raw_text`, `location_json`, `extraction_method`; immutable evidence |
| `candidate` | `run_id`, `revision`, `name`, `sequence_spans`, `normalized_sequence`, `type`, `completeness`, `status` |
| `qc_issue` and `review` | `candidate_id`, `revision`, `rule_id`, `severity`, `resolution`; approver and approved revision |
| `sequence_entity` | `id`, `tenant_id`, `type`, `canonical_sequence`, `length`, `sha256`; compare full content after a hash match |
| `record` and `version` | `project_id`, `name_key`; `record_id`, `version_no`, `sequence_id`, `previous_version_id` |
| `provenance` and `audit` | Links from versions to candidates, source files, and evidence; actor, event, before/after values, timestamp |

Apply a unique constraint to `(tenant_id, type, sha256)` for sequence entities and compare full sequence content to guard against hash collisions. Constrain name records by `(project_id, name_key)` and versions by `(record_id, version_no)`. Application records govern project access; reusing a sequence entity across projects must not reveal the existence of other projects. [1]

| API | Behavior |
| --- | --- |
| `POST /v1/uploads` | Check project permissions; create upload session and return `file_id` |
| `POST /v1/uploads/{id}/complete` | Verify byte count and hash; idempotently create processing task; return `202` |
| `GET /v1/jobs/{id}` | Return stage, status, counts, and safe error summary; support polling |
| `GET /v1/jobs/{id}/candidates` | Paginate candidates and issues; do not expose unauthorized projects |
| `PATCH /v1/candidates/{id}` | Include revision in `If-Match`; update and trigger revalidation |
| `POST /v1/reviews` | Approve or reject a specified revision; require reviewer permission |
| `POST /v1/commits` | Accept approved revisions and `Idempotency-Key`; return per-item results |
| `GET /v1/records` | Filter by name, project, length, and other fields; cursor pagination |
| `GET /v1/records/{id}/export` | Authorized FASTA export with an explicit version and escaped header |

The standard error format includes `code`, `message`, `request_id`, `details`, and `retryable`. Use `400` for malformed requests, `403` for insufficient permissions, `409` for revision or business conflicts, `413` for size limits, `422` for unacceptable content, and `429` for rate limiting. Reauthorize downloads of originals and evidence; temporary links must be short-lived.

## 9. Security, Operations, and Quality Monitoring

### File and Model Security

Use an extension allowlist, detected file-type checks, and limits on file size and decompression. Isolate and scan originals; do not execute macros, formulas, or embedded objects. Limit parser memory, execution time, network access, and filesystem permissions. Treat filenames as display data, not storage paths. Downloads require authorization. [2]

Uploaded content and filenames are untrusted data and cannot alter system instructions. AI may read only authorized document blocks and return structured extraction results; it cannot invoke SQL, shell commands, external search, or arbitrary URLs. Send only task-essential content to the model, and do not write sequences into ordinary logs.

Allow only organization-approved model endpoints by default. Before launch, confirm deployment region, data retention, use for training, and deletion arrangements. If a configuration does not meet organizational requirements, disable the AI path while retaining deterministic parsing and manual entry. Project permissions cover originals, evidence, search, export, and backup restoration.

### Proposed Initial Capacity and Service Targets

| Metric | Proposed Initial Value and Measurement Conditions |
| --- | --- |
| Upload limits | 20 MB per file; 50 files per batch; 100 pages per PDF |
| Extraction limits | 1,000 candidates per file; 100,000 residues per sequence; explicitly stop when exceeded |
| Workload | 100 registered users; 10 concurrent extraction tasks as the initial load-test baseline |
| Search performance | p95 below 1 second with 100,000 application record versions and 10 concurrent queries |
| Processing performance | Excluding queue time, p95 below 60 seconds for text files up to 1 MB and 100 records |
| OCR performance | p95 below 180 seconds for files up to 20 pages; a Phase 2 target |
| Recovery objectives | Proposed RPO of 24 hours and RTO of 8 hours; complete a recovery exercise before launch |

These are proposed acceptance budgets and must be calibrated through load testing after infrastructure and model selection. Exceeding page, token, duration, or decompressed-byte limits must result in an explicit failure or manual handling; the system must not truncate content and report success.

### Monitoring and Change Control

Track complete-extraction rates, missed-candidate rates, name-association error rates, manual character-correction rates, review time, stage failure rates, latency, and model costs by format and version. Ordinary telemetry contains only IDs, counts, and error codes. Troubleshooting involving sensitive content uses a controlled audit channel.

Every model, parser, prompt, or QC rule change runs against the same frozen test set, and results are retained. Automatic ingestion has a separate switch that can be disabled by format and version. Rollbacks affect new tasks and do not rewrite historical published records. Configure retention periods for originals and application records after approval by the data owner; deletions must be auditable.

## 10. Test Data and Development Acceptance

### Benchmark Set and Metric Definitions

Prepare at least 200 representative files checked by two people, covering all first-release formats, different sequence lengths, and multisequence documents. Maintain separate adversarial and exception test sets. Split development and frozen acceptance sets by file source or template family to avoid near-duplicate leakage. Gold-standard annotations include every sequence, its corresponding name, evidence, and expected blocking issues.

Measure whole-sequence accuracy by exact equality after normalization; character-level averages must not conceal single-residue errors. Also measure record recall and name-association accuracy. Include missed records in the recall denominator rather than measuring only records found by the system. The denominator for the automatic-acceptance error rate is the set of automatically accepted records; report coverage and sample size as well.

| Acceptance Area | First-Release Passing Criterion |
| --- | --- |
| Deterministic parsing | 100% exact matches for full sequences and names in the standard FASTA gold set |
| Nonstandard text-based extraction | Whole-sequence accuracy ≥99%, recall ≥98%, and name-association accuracy ≥98% on the frozen set |
| Published ingestion | Records after human review in the acceptance workflow match the gold standard exactly, with 100% agreement |
| Blocking behavior | Every designated `BLOCK` case in the exception set is intercepted; no silent truncation |
| Traceability | Every published record links to its original, evidence, QC results, and approved revision |
| Concurrency and idempotency | Duplicate submissions create no duplicate versions; stale approvals and unauthorized commits fail |
| Recovery | Processing resumes after worker interruption; partially successful batches can be retried; no partially written transactional items |

### Required End-to-End Cases

| ID | Test Case |
| --- | --- |
| T01 | Name in filename and one sequence in the body |
| T02 | Multiple FASTA records |
| T03 | Multiple names and sequences in Word |
| T04 | Heavy and light chains in a table |
| T05 | Conflicting names |
| T06 | Position numbering and page headers mixed into sequence text |
| T07 | Unprocessed text boxes or tracked changes |
| T08 | Ellipses or truncated AI output |
| T09 | Name without sequence content |
| T10 | Same name/different sequences and same sequence/different names |
| T11 | Duplicate tasks and duplicate commits |
| T12 | Two users editing concurrently |
| T13 | Permissions revoked before commitment |
| T14 | A file containing prompt-injection instructions |
| T15 | Misleading extensions, limit violations, and corrupted files |
| T16 | Earlier approvals invalidated by re-extraction |
| T17 | Ambiguity between nucleic acid and protein types |
| T18 | Cross-project deduplication without information disclosure |
| T19 | Very long sequences are not reproduced as full model-generated output |
| T20 | Late results cannot be committed after task cancellation |

### Separate Acceptance for Automatic Ingestion

The first release does not impose a mandatory automatic-acceptance percentage. For subsequent releases, run each proposed automatic-acceptance scope in shadow mode and report error counts and confidence intervals. Zero observed errors does not mean zero risk. For example, with zero errors in independent samples, the approximate one-sided 95% upper bound on the error rate is `3/n`. Even 3,000 samples constrain it only to approximately 0.1%; sample representativeness must still be assessed.

## 11. Development Breakdown and Launch Plan

| Phase | Development Work | Exit Criteria |
| --- | --- | --- |
| A: Contracts and samples | Sample files, gold standards, IR schema, QC rules, UI sketches | Review passed; expected behavior defined for every boundary condition |
| B: Basic end-to-end workflow | Authentication, projects, upload, FASTA, candidates, review, published ingestion | Single-record and multirecord FASTA workflows pass end to end |
| C: Intelligent extraction | DOCX, TXT, CSV, XLSX, PDF, AI localization, name association | Frozen-set metrics and coverage-warning tests pass |
| D: Hardening and pilot | Idempotency, concurrency, security, performance, backups, legacy migration | Required cases pass; pilot users can complete their work |
| E: Further enhancements | OCR, complex layouts, automatic acceptance, additional formats | Each enhancement passes its separate quality gate |

### Deliverables and Responsibilities

The development team delivers source code and deployment configuration, database migrations, OpenAPI definitions, DocumentIR and candidate JSON Schemas, versioned extraction templates, a QC rule registry, automated tests and benchmark evaluation scripts, and operations and rollback manuals. The research data owner provides samples and gold standards and confirms naming and versioning rules. The test lead maintains the frozen acceptance set.

### Legacy System Migration

First export legacy IDs, names, sequences, projects, permissions, and timestamps, and create a read-only snapshot. Run the same deterministic QC while preserving `legacy_id` and the migration batch. If originals are unavailable, explicitly set `source=legacy_import`; do not fabricate extraction evidence. Route anomalous records to review without silent cleanup.

Perform a migration dry run and reconcile total legacy records, unique sequence counts, rejected records, hashes, and permissions. Keep the old system read-only during the pilot. Before cutover, freeze writes, synchronize incremental changes, and complete full reconciliation before switching the application entry point. A rollback must preserve and export records created after cutover so that restoring the old database does not lose new data.

### Configuration to Confirm at Project Start

The following decisions do not prevent development work from being divided according to this design, but must be finalized before launch: enterprise sign-in method, existing infrastructure, approved model endpoints, data retention periods, user scale, whether text-based PDF is included in the first release, and the business policy for extended residue characters. Use the capacity and scope in this document as defaults; update the acceptance set when these change.

### Technical References

1. [PostgreSQL Documentation — Constraints](https://www.postgresql.org/docs/17/ddl-constraints.html). Basis for database constraint design; does not replace application-level version checks. Accessed September 29, 2026.
2. [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html). Basis for file-type, size, isolation, and upload security controls. Accessed September 29, 2026.
