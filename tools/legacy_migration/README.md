# Legacy migration

Imports a legacy export through the same QC as uploads, and reconciles the result (design, "Legacy System Migration").

```sh
uv run python tools/legacy_migration/migrate.py export.json \
    --project PROJECT_ID --legacy-project "Antibodies" --operator migration@corp \
    [--dry-run] [--report report.json]
```

## Input

The input is a JSON export from the read-only legacy snapshot. The tool imports only the rows whose `project` equals `--legacy-project`.

```json
{"source_system": "LIMS", "exported_at": "2026-09-20T10:00:00+00:00",
 "records": [{"legacy_id": "L-1", "project": "Antibodies", "name": "A1", "sequence": "MKT…",
              "molecule_type": "protein", "created_at": "2019-03-01T08:00:00+00:00", "updated_at": null}],
 "permissions": [{"subject": "alice@corp", "project": "Antibodies", "role": "reviewer"}]}
```

## What it does

- **Snapshot.** The export is stored as an ordinary source file: it is scanned, gets a SHA-256, and gets its own task and run (parser version `legacy-export-1`). The snapshot is the batch's provenance.
- **Rejected rows.** A row is rejected, with a reason, when it:
  - has no legacy ID (`missing_legacy_id`);
  - shares its legacy ID with another row (`duplicate_legacy_id`);
  - has a non-text field (`invalid_field`);
  - has an unknown molecule type (`unknown_molecule_type`);
  - has a timestamp without a zone (`invalid_timestamp`).

  Rejected rows are listed in the report, never dropped silently.
- **QC.** Every other row becomes a `legacy_import` candidate:
  - The sequence is held as typed text with no evidence spans, because the original documents are unavailable. Evidence is never fabricated.
  - The name keeps its source `legacy_import`.
  - Rows are imported in legacy `created_at` order, and the same deterministic QC runs on each.
  - QC09 and QC10 see everything already published, including earlier rows of the same export. A later legacy edit of a name therefore needs an explicit version decision.
- **Commit.** When QC leaves nothing for a reviewer to decide, the operator approves and commits the row through the normal commit transaction (idempotency key `legacy:<batch>`). Everything else waits in the review queue under the batch's task. Reviewers handle those candidates in the web app like any other.
- **Traceability.** `legacy_record` (migration 0003, immutable) keeps the legacy ID, the original name, the legacy timestamps, the hash of the exact exported sequence, and the candidate. `legacy_batch` keeps the operator, the source system and the final report.
- **Re-runs.** A re-run skips rows whose name and sequence have not changed since their last import (`unchanged_since_last_import`). Changed rows come in as new candidates. This is the incremental sync before cutover.

## Report

Sequences never appear in the report. The report is printed as JSON; `--report` also writes it to a file. It covers the whole export against the current state of the system:

| Field | Meaning |
|---|---|
| `counts` | Legacy records; rejected; accepted; unchanged since the last import; committed; pending review; closed without publishing (rejected or archived by a reviewer) |
| `balanced` | Records = rejected + accepted, and accepted = committed + pending + closed |
| `unique_sequences` | Distinct normalized sequences accepted, and distinct published sequences |
| `hash_mismatches` | Committed rows whose published sequence hash differs from the hash of the normalized legacy sequence; this must be empty |
| `rejected`, `pending_review` | Per row: the reason or the QC rules |
| `permissions` | Legacy grants matched, missing in the new system, with unmapped roles, and grants that exist only in the new system |

Exit status:

- 0: balanced with no hash mismatches.
- 1: otherwise.
- 2: usage errors.

A dry run writes nothing. It predicts the outcome, treating earlier rows of the export as published.

## Cutover checklist

1. Keep the legacy system read-only. Export, then run `--dry-run` and review the report with the data owner.
2. Import. Reviewers clear `pending_review`. Grant the `missing` permissions with `sequence_vault.entrypoints.admin grant`.
3. Before cutover, freeze legacy writes, export again and import again. Only changed rows come in. Repeat until `pending_review` is empty and the report is balanced.
4. Switch the entry point. For a rollback, export every record created after cutover first (see `docs/operations`).
