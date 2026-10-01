"""Deterministic first-pass extraction (design section 4, "Two-Step Extraction").

Turns FASTA records and sequence-like paragraphs into extraction records that point at
evidence. Names follow section 5: an in-document name first; the filename stem only when the
file holds a single sequence, and then always for confirmation.
"""

import re
from pathlib import PurePath
from typing import Any

from sequence_vault.application.errors import LimitExceeded
from sequence_vault.domain.naming import name_key

Json = dict[str, Any]

RESIDUE_LETTERS = frozenset("ACDEFGHIKLMNPQRSTVWYBZJXUOacdefghiklmnpqrstvwybzjxuo")
MIN_SEQUENCE_LENGTH = 10
_RESIDUE_RUN = re.compile(r"[A-Za-z]{20,}")


def is_sequence_like(text: str) -> bool:
    """Residue text, not prose: almost only residue letters, a single letter case, and long
    runs (sequences are written continuously or in blocks of ten). Every Latin letter is a
    residue code, so letters alone cannot tell sequences from words."""
    tokens = ["".join(c for c in token if not c.isdigit()) for token in text.split()]
    tokens = [token for token in tokens if token]
    characters = "".join(tokens)
    if len(characters) < MIN_SEQUENCE_LENGTH:
        return False
    residues = sum(1 for c in characters if c in RESIDUE_LETTERS or c in "*-.")
    letters = [c for c in characters if c.isalpha()]
    single_case = all(c.isupper() for c in letters) or all(c.islower() for c in letters)
    mean_token = len(characters) / len(tokens)
    return residues / len(characters) >= 0.95 and single_case and mean_token >= 8


def _record(names: list[Json], spans: list[Json], status: str) -> Json:
    return {
        "names": names,
        "molecule_type": "protein",
        "sequence_spans": spans,
        "association_status": status,
        "observations": [],
    }


def _whole(block: Json) -> Json:
    return {"block_id": block["block_id"], "start": 0, "end": len(block["raw_text"]), "order": 1}


def _fasta_name(block: Json) -> Json | None:
    token = block["raw_text"].split(maxsplit=1)[0] if block["raw_text"].strip() else ""
    if not token:
        return None
    start = block["raw_text"].index(token)
    return {
        "value": token,
        "source": "fasta_header",
        "evidence": {"block_id": block["block_id"], "start": start, "end": start + len(token)},
    }


def _fasta_records(blocks: list[Json]) -> list[Json]:
    records = []
    by_id = {block["block_id"]: block for block in blocks}
    for block in blocks:
        if block["type"] != "fasta_header":
            continue
        name = _fasta_name(block)
        body = by_id.get("s" + block["block_id"][1:])
        spans = [_whole(body)] if body is not None else []
        records.append(
            _record([name] if name else [], spans, "unambiguous" if name else "ambiguous")
        )
    return records


def _paragraph_records(blocks: list[Json], unresolved: list[str]) -> list[Json]:
    records = []
    for block in blocks:
        if block["type"] not in {"paragraph", "text"}:
            continue
        raw = block["raw_text"]
        if is_sequence_like(raw):
            records.append(_record([], [_whole(block)], "ambiguous"))
            continue
        first, _, rest = raw.partition("\n")
        if rest and is_sequence_like(rest) and not is_sequence_like(first) and len(first) <= 120:
            heading = first.strip().rstrip(":\uff1a")
            start = first.index(heading) if heading else 0
            names = (
                [
                    {
                        "value": heading,
                        "source": "heading",
                        "evidence": {
                            "block_id": block["block_id"],
                            "start": start,
                            "end": start + len(heading),
                        },
                    }
                ]
                if heading
                else []
            )
            span = {
                "block_id": block["block_id"],
                "start": len(first) + 1,
                "end": len(raw),
                "order": 1,
            }
            records.append(_record(names, [span], "unambiguous" if names else "ambiguous"))
        elif _RESIDUE_RUN.search(raw):
            unresolved.append(block["block_id"])
    return records


def _apply_filename(records: list[Json], file_name: str) -> None:
    """Filename stem as a candidate name only for a single sequence (T01, T05)."""
    sequences = [record for record in records if record["sequence_spans"]]
    stem = PurePath(file_name).stem.strip()
    if len(sequences) != 1 or not stem:
        return
    record = sequences[0]
    filename = {"value": stem, "source": "filename", "evidence": None}
    if not record["names"]:
        record["names"] = [filename]
        record["association_status"] = "ambiguous"  # needs confirmation
    elif all(name_key(n["value"]) != name_key(stem) for n in record["names"]):
        record["names"].append(filename)
        record["association_status"] = "conflicting"


def extract(
    document: Json,
    file_name: str,
    *,
    max_candidates: int,
    max_residues: int,
) -> Json:
    """Return an extraction result (extraction-result.schema.json) for a DocumentIR."""
    blocks = document["blocks"]
    unresolved = list(document["coverage"]["unresolved_blocks"])
    if any(block["type"] == "fasta_header" for block in blocks):
        records = _fasta_records(blocks)
        leftovers = [b for b in blocks if b["type"] == "text"]
        records += _paragraph_records(leftovers, unresolved)
    else:
        records = _paragraph_records(blocks, unresolved)
    _apply_filename(records, file_name)
    if len(records) > max_candidates:
        raise LimitExceeded(
            f"{len(records)} candidates exceed the limit of {max_candidates}.",
            code="candidate_limit",
        )
    by_id = {block["block_id"]: block["raw_text"] for block in blocks}
    for record in records:
        length = sum(
            sum(1 for c in by_id[s["block_id"]][s["start"] : s["end"]] if not c.isspace())
            for s in record["sequence_spans"]
        )
        if length > max_residues:
            raise LimitExceeded(
                f"A sequence of {length} characters exceeds the limit of {max_residues}.",
                code="sequence_limit",
            )
    coverage = dict(document["coverage"])
    coverage["unresolved_blocks"] = sorted(set(unresolved), key=unresolved.index)
    if coverage["unresolved_blocks"] and not coverage.get("warnings"):
        coverage["warnings"] = ["Some blocks contain residue-like text that was not extracted."]
    return {
        "schema_version": "1.0",
        "file_id": document["file_id"],
        "run_id": document["run_id"],
        "records": records,
        "coverage": coverage,
    }
