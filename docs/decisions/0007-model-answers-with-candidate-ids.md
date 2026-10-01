# ADR 0007: The model answers with candidate ids, not offsets

Status: proposed; amends the extraction contract of ADR 0002 for the model step only. Basis: design v1.0 sections 4 and 9.

The design asks the model to return block ids and code-point offsets. Language models count characters unreliably, especially in long residue strings and mixed CJK text, so raw offsets would often point one character off. The design also says rules find candidate spans first and the model decides how names relate to them.

Decisions:

- Rules number every candidate: spans (`S1…`) from sequence-like blocks and residue runs inside prose, and names (`N1…`) from rule names, short blocks, headings, table cells and the file name. Each carries exact code-point offsets computed by software.
- The model (`prompts/extraction/v1/system.md`) answers only with those ids, grouped into records with an association status and observations. The answer schema fits structured outputs (closed objects, no string or number constraints).
- `application/model_assist.py` resolves the ids into an extraction result that satisfies `extraction-result.schema.json` and the domain cross-checks. Unknown ids or spans claimed twice get one repair attempt; after that, or after a refusal, the rule result stays with a coverage warning (QC08), so a person decides.
- The model is called only when rules leave something open (unresolved blocks or non-unambiguous records) and never for FASTA. Blocks over 20,000 code points are summarized, never sent (T19).
- The reference adapter uses Claude Opus 5.5 at `medium` effort with the server-side refusal fallback on the Claude API; Bedrock and Vertex AI clients are supported without it. The model, prompt and schema versions are stored on each extraction run.

Consequences: no model text is ever stored as sequence or name content; prompt injection can at most mis-group candidates, which QC and review catch (T14). The extraction contract stored per run is unchanged.
