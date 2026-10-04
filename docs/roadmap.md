# Development roadmap and acceptance mapping

Track implementation and evidence against the original specification, especially section 10. The delivery plans P1–P7 and their status are in [implementation-plan.md](implementation-plan.md), section 3.

| Phase | Work locations | Required gate | Status |
| --- | --- | --- | --- |
| A: contracts and samples | `packages/contracts`, `config`, `prompts`, `tests/fixtures`, `tests/benchmarks` | Review schemas, annotations, QC boundaries, and UI sketches; prepare at least 200 doubly checked representative files with source/template-separated development and frozen sets | Contracts, QC registry, prompt v1 and fixtures done. **Open:** the 200-file representative set, owed by the data owner and test lead |
| B: basic end to end | Backend domain/application/API/workers, FASTA parser, upload/review UI, migrations | Authentication/projects/upload and single/multiple FASTA flows publish exactly the reviewed sequence | Done (P1–P5) |
| C: intelligent extraction | Parser registry, model adapter, evidence UI, evaluation tool | DOCX/TXT/CSV/XLSX/text-PDF coverage warnings and frozen accuracy/recall/name metrics pass | Done (P6) on the synthetic set from `tools/evaluation`. **Open:** repeat on the representative frozen set |
| D: hardening and pilot | Integration/security/E2E tests, infrastructure, operations, legacy tools | Concurrency, idempotency, cancellation, authorization, load and recovery tests pass; pilot and migration reconciliation succeed | Done (P7) except the pilot and a reconciliation on real legacy data |
| E: enhancements | New parsers/OCR and policy versions | Separate acceptance gate for OCR, complex layouts, and each proposed automatic-ingestion scope | Not started |

## Required cases

| Case | Coverage |
| --- | --- |
| T01 | Filename name plus one body sequence |
| T02 | Multiple FASTA records |
| T03 | Multiple Word names/sequences |
| T04 | Antibody heavy/light chains in a table |
| T05 | Conflicting names |
| T06 | Position numbering and page headers |
| T07 | Text boxes and tracked changes |
| T08 | Ellipses or truncated extraction |
| T09 | Name without sequence |
| T10 | Name/sequence duplicates and explicit version decisions |
| T11 | Duplicate tasks and commits |
| T12 | Concurrent edits |
| T13 | Permission revoked before commit |
| T14 | Prompt injection in uploaded content |
| T15 | Misleading extensions, limits, corruption |
| T16 | Re-extraction invalidates older approvals |
| T17 | Protein/nucleic-acid ambiguity |
| T18 | Cross-project deduplication preserves access boundaries |
| T19 | Long sequences reconstructed from spans, never model-generated bodies |
| T20 | Cancellation prevents late-result commitment |

Preserve gold annotations for every expected sequence, name, location, and blocking issue. Report exact whole-sequence equality, record recall including misses, and name association accuracy. Post-review publication must match gold exactly. No benchmark success on representative data is claimed yet.
