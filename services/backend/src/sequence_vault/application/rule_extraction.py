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
        spans = [_whole_span(body)] if body is not None else []
        records.append(
            _record([name] if name else [], spans, "unambiguous" if name else "ambiguous")
        )
    return records


_LABEL = re.compile(r"[:\uff1a]")


def _heading_name(line: str) -> tuple[str, int]:
    """Name and its code-point offset in a heading line. A label before an ASCII or
    full-width colon is dropped ("Name: RSPO3" names RSPO3); with nothing after the colon,
    the text before it is the name ("Light chain:")."""
    label = _LABEL.search(line)
    if label is not None:
        after = line[label.end() :]
        if after.strip():
            value = after.strip()
            return value, label.end() + after.index(value)
        line = line[: label.start()]
    value = line.strip()
    return value, (line.index(value) if value else 0)


def _whole_span(block: Json, order: int = 1) -> Json:
    return {
        "block_id": block["block_id"],
        "start": 0,
        "end": len(block["raw_text"]),
        "order": order,
    }


def _evidence(block: Json) -> Json:
    return {"block_id": block["block_id"], "start": 0, "end": len(block["raw_text"])}


def _adjacent(first: Json, second: Json) -> bool:
    """Consecutive Word paragraphs: structural continuity for joining spans."""
    a, b = first["location"], second["location"]
    return bool(
        a["kind"] == b["kind"] == "docx_paragraph"
        and b["paragraph_index"] == a["paragraph_index"] + 1
    )


def _is_heading(block: Json) -> bool:
    raw = block["raw_text"]
    return "\n" not in raw.strip() and len(raw) <= 120 and not is_sequence_like(raw)


def _heading(block: Json, line: str, offset: int = 0) -> list[Json]:
    value, start = _heading_name(line)
    if not value:
        return []
    begin = offset + start
    return [
        {
            "value": value,
            "source": "heading",
            "evidence": {"block_id": block["block_id"], "start": begin, "end": begin + len(value)},
        }
    ]


def _paragraph_records(blocks: list[Json], unresolved: list[str]) -> list[Json]:
    records: list[Json] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        raw = block["raw_text"]
        if is_sequence_like(raw):
            group = [block]
            while (
                index + len(group) < len(blocks)
                and _adjacent(group[-1], blocks[index + len(group)])
                and is_sequence_like(blocks[index + len(group)]["raw_text"])
            ):
                group.append(blocks[index + len(group)])
            previous = blocks[index - 1] if index else None
            names = (
                _heading(previous, previous["raw_text"])
                if previous is not None and _adjacent(previous, block) and _is_heading(previous)
                else []
            )
            record = _record(
                names,
                [_whole_span(b, order) for order, b in enumerate(group, start=1)],
                "unambiguous" if names else "ambiguous",
            )
            if len(group) > 1:
                record["observations"].append(
                    {
                        "kind": "cross_block_join",
                        "message": f"Joined {len(group)} consecutive paragraphs into one sequence.",
                        "evidence": [_evidence(b) for b in group],
                    }
                )
            records.append(record)
            index += len(group)
            continue
        first, _, rest = raw.partition("\n")
        if rest and is_sequence_like(rest) and not is_sequence_like(first) and len(first) <= 120:
            span = {
                "block_id": block["block_id"],
                "start": len(first) + 1,
                "end": len(raw),
                "order": 1,
            }
            names = _heading(block, first)
            records.append(_record(names, [span], "unambiguous" if names else "ambiguous"))
        elif _RESIDUE_RUN.search(raw):
            unresolved.append(block["block_id"])
        index += 1
    return records


_NAME_KEYS = (
    "名称",
    "名字",
    "编号",
    "克隆",
    "样品",
    "抗体",
    "蛋白",
    "name",
    "id",
    "clone",
    "sample",
    "antibody",
    "construct",
)
_SEQUENCE_KEYS = ("序列", "sequence", "seq")
_CHAIN_KEYS = ("重链", "轻链", "heavy", "light", "vh", "vl", "hc", "lc")


def _matches(text: str, keys: tuple[str, ...]) -> bool:
    value = text.strip().casefold()
    for key in keys:
        if key.isascii():
            if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", value):
                return True
        elif key in value:
            return True
    return False


def _table_key(block: Json) -> tuple[str, str]:
    location = block["location"]
    if location["kind"] == "docx_table_cell":
        return ("docx", str(location["table_index"]))
    return ("sheet", str(location["worksheet"]))


def _table_records(blocks: list[Json], unresolved: list[str]) -> list[Json]:
    tables: dict[tuple[str, str], dict[tuple[int, int], Json]] = {}
    for block in blocks:
        location = block["location"]
        tables.setdefault(_table_key(block), {})[(location["row"], location["column"])] = block
    records: list[Json] = []
    for grid in tables.values():
        rows = sorted({row for row, _ in grid})
        header_row = next(
            (
                row
                for row in rows
                if any(
                    _matches(cell["raw_text"], _SEQUENCE_KEYS + _CHAIN_KEYS)
                    and not is_sequence_like(cell["raw_text"])
                    for (r, _), cell in grid.items()
                    if r == row
                )
            ),
            None,
        )
        if header_row is None:
            records += _headerless_rows(grid, rows)
            continue
        header = {col: cell for (row, col), cell in grid.items() if row == header_row}
        sequence_columns = sorted(
            col
            for col, cell in header.items()
            if _matches(cell["raw_text"], _SEQUENCE_KEYS + _CHAIN_KEYS)
        )
        name_column = next(
            (
                col
                for col, cell in sorted(header.items())
                if col not in sequence_columns and _matches(cell["raw_text"], _NAME_KEYS)
            ),
            next((col for col in sorted(header) if col not in sequence_columns), None),
        )
        for row in rows:
            if row <= header_row:
                continue
            name_cell = grid.get((row, name_column)) if name_column is not None else None
            names = (
                [
                    {
                        "value": name_cell["raw_text"].strip(),
                        "source": "table_cell",
                        "evidence": _name_evidence(name_cell),
                    }
                ]
                if name_cell is not None and not is_sequence_like(name_cell["raw_text"])
                else []
            )
            for col in sequence_columns:
                cell = grid.get((row, col))
                if cell is not None and is_sequence_like(cell["raw_text"]):
                    record = _record(
                        list(names),
                        [_whole_span(cell)],
                        "unambiguous" if names and len(sequence_columns) == 1 else "ambiguous",
                    )
                    if len(sequence_columns) > 1:
                        record["observations"].append(
                            {
                                "kind": "unclear_mapping",
                                "message": f"Chain column '{header[col]['raw_text'].strip()}': "
                                "add the chain label to the name.",
                                "evidence": [_evidence(header[col])],
                            }
                        )
                    records.append(record)
                elif cell is None and names and len(sequence_columns) == 1:
                    records.append(_record(list(names), [], "unambiguous"))
                elif cell is not None and _RESIDUE_RUN.search(cell["raw_text"]):
                    unresolved.append(cell["block_id"])
    return records


def _name_evidence(cell: Json) -> Json:
    raw = cell["raw_text"]
    value = raw.strip()
    start = raw.index(value)
    return {"block_id": cell["block_id"], "start": start, "end": start + len(value)}


def _headerless_rows(grid: dict[tuple[int, int], Json], rows: list[int]) -> list[Json]:
    """Without a header, pair each sequence cell with the text cells of its own row."""
    records: list[Json] = []
    for row in rows:
        cells = sorted(((col, cell) for (r, col), cell in grid.items() if r == row))
        texts = [cell for _, cell in cells if not is_sequence_like(cell["raw_text"])]
        for col, cell in cells:
            if not is_sequence_like(cell["raw_text"]):
                continue
            left = [c for c in texts if c["location"]["column"] < col]
            names = (
                [
                    {
                        "value": left[-1]["raw_text"].strip(),
                        "source": "table_cell",
                        "evidence": _name_evidence(left[-1]),
                    }
                ]
                if left
                else []
            )
            status = "unambiguous" if len(texts) == 1 and names else "ambiguous"
            records.append(_record(names, [_whole_span(cell)], status))
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
    elif any(c.isdigit() for c in stem) and all(
        name_key(n["value"]) != name_key(stem) for n in record["names"]
    ):
        # Only a stem that looks like an identifier (lab names carry numbers) can conflict;
        # generic names such as "results" or "table" are not names.
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
        prose = [b for b in blocks if b["type"] in {"paragraph", "text"}]
        cells = [b for b in blocks if b["type"] == "table_cell"]
        records = _paragraph_records(prose, unresolved) + _table_records(cells, unresolved)
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
