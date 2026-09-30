# Shared contracts

`schemas/v1` contains draft strict JSON Schemas for immutable DocumentIR, structured extraction output, and review-facing candidates. `examples` contains synthetic wire-format examples. `api/README.md` maps the required HTTP operations; OpenAPI generation is deferred until the API framework is selected.

These schemas capture the core shape of design sections 4 and 8 and need Phase A contract review. They are not a production validator. Cross-field checks (block IDs, span bounds, source identity, assembly order uniqueness/continuity, policy resolutions, authorization and revisions) require backend validation. Schema validation alone cannot authorize publication.

Persist `schema_version` with every extraction run. Use Unicode code points and half-open text ranges everywhere. Generate frontend types from the reviewed schemas once tooling is selected; do not maintain divergent copies.
