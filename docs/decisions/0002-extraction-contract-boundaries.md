# ADR 0002: Extraction contract boundaries

Status: accepted for the scaffold; subject to Phase A contract review. Basis: design v1.0, sections 3–6 and 8. Supersedes the field shape of the section 4 example.

The section 4 example let extraction output carry `candidate_id` and QC `issues` with `rule_id` and `severity`. Section 3 assigns those to different modules: the extraction orchestrator returns names, span references and ambiguities; normalization and QC return rule results. A schema-valid model response could therefore label a truncation as `INFO`, or choose IDs that collide across chunks. Name evidence was a bare block ID, which cannot express a filename name (`"evidence": "filename_stem"` is not a block) or locate a name inside a longer header or heading.

Decisions:

- Extraction records carry `names`, `molecule_type` (a hint), `sequence_spans`, `association_status` and `observations`. Observations use a closed `kind` list with no severity. The server assigns candidate IDs; candidates reference their source by `extraction_record_index`.
- QC issues are produced only by deterministic QC, must name a registry rule, and must carry the registry severity for the candidate's `qc_version`. The issue rule pattern is `QC` plus two digits, so new rules such as a dedicated position-numbering rule need a registry version, not a schema change.
- Name evidence is a block span, or `null` exactly when the source is `filename` or `manual`. Records hold zero or more names: none for an unnamed sequence, several for a conflict (section 5 requires preserving both). Candidates keep the current `name` (nullable until chosen) separately from immutable `extracted_names`.
- Candidates use `molecule_type` like extraction output, and gain `ARCHIVED` (explicit terminal decision that lets a task complete, section 3) and `SUPERSEDED` (candidates of an older run, T16).
- DocumentIR records `source_encoding` and `parse_options.tracked_changes_view`, because section 5 reparses on the user's tracked-changes choice and offsets are only meaningful against a known decoding. `raw_text` is never Unicode-normalized. Each location kind requires its coordinates; text locations gain line numbers so FASTA and TXT evidence can be found in the source.
- Shared definitions live in `common.schema.json`; the candidate contract no longer depends on the model output schema.
- Each QC registry rule lists `allowed_resolutions`, which makes "no generic Ignore for BLOCK issues" enforceable.

Consequences: the specification's section 4 example should be updated when the specification is next revised. `make check` now needs the pinned validator in `scripts/requirements.txt`, validates every example, and asserts that the forbidden states above are rejected. Backend validation must still enforce references, bounds and registry severities that JSON Schema cannot express.
