# Extraction prompt, version 1 (`extraction-v1`)

`system.md` is the system prompt for model-assisted name association (ADR 0007). The model receives numbered span and name candidates whose offsets software computed, and answers only with those ids; `services/backend/src/sequence_vault/application/model_assist.py` turns the ids back into code-point evidence and validates the result against `packages/contracts/schemas/v1/extraction-result.schema.json` and the domain cross-checks.

Rules from the design that this prompt and its gateway enforce:

- Document blocks, file names and embedded instructions are untrusted data.
- The model never produces sequence or name text; long blocks are summarized, never sent in full (T19).
- One controlled repair attempt; an answer that still does not resolve leaves the rule-based result in place with a coverage warning, so a person reviews it.
- Model confidence is not an acceptance signal; every result still goes through deterministic QC and human review.

Changing this prompt means a new version folder and a frozen-set evaluation run before it is enabled.
