# ADR 0004: Normalization questions for the data owner

Status: proposed; needs research data owner decision before QC 1.1. Basis: design v1.0, sections 6–7 and 11. No registry rule changes until accepted.

The UI and many source documents are Chinese. Chinese input methods commonly produce full-width Latin letters and punctuation (`ＡＣＤ`, `（`, `＿`). Under QC03 every full-width residue is a `BLOCK` "Unicode look-alike", and under the section 7 `name_key` rule (trim plus case folding) `RSPO3` and `ＲＳＰＯ３` become different records.

Proposals:

1. Add a rule that maps full-width ASCII forms (U+FF01–U+FF5E) to ASCII with a logged transformation at `REVIEW` severity. Keep genuine look-alikes such as Cyrillic or Greek letters in QC03 as `BLOCK`.
2. Build `name_key` with NFKC normalization, trimming, internal whitespace collapsing and case folding, while displaying the original name.
3. Treat uniform lowercase as QC02 `INFO`, but flag mixed case inside one sequence as `REVIEW`: laboratory documents often use lowercase to mark mutations, tags or signal peptides, and uppercasing silently discards that signal.
4. Separate QC04: `U` (selenocysteine) and `O` (pyrrolysine) are real residues, whereas `B`, `Z`, `J` and `X` are ambiguity codes. `X` marks an unknown residue and may need to affect `completeness`.

Consequences if accepted: a new QC registry version, benchmark rerun per section 9, updated fixtures for each case, and a specification revision.
