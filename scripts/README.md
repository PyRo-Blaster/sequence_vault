# Repository checks

`check_scaffold.py` validates the synthetic contract examples against the draft JSON Schemas, asserts that the schemas reject forbidden states (model-assigned IDs or severities, unsupported name evidence, incomplete locations), and checks cross-example span consistency and QC registry invariants. It is a development check, not the backend validator: the backend must still enforce block references, span bounds, authorization and revisions.

Its dependencies come from the `dev` group in the root `pyproject.toml`. Run it with `make scaffold`.
