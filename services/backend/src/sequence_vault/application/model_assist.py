"""Model-assisted name association (design section 4, "Two-Step Extraction"; ADR 0007).

Rules number every candidate span and name with exact code-point offsets. The model answers
only with those IDs: which spans form a record, in which order, and which names belong to it.
Software turns the IDs back into evidence, so model text is never stored as sequence or name
content, and an answer that does not resolve cleanly is retried once and then set aside.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Protocol

from sequence_vault.application.contract_mapping import records_from_extraction
from sequence_vault.application.rule_extraction import is_sequence_like
from sequence_vault.domain.extraction import check_extraction

Json = dict[str, Any]
SUMMARY_LIMIT = 20_000  # longer blocks reach the model as a summary, never in full (T19)
# One continuous run, or blocks of ten separated by spaces (the usual printed layout).
_RESIDUE_RUN = re.compile(r"(?:[A-Za-z]{10,}[ \t]+)+[A-Za-z]{10,}|[A-Za-z]{20,}")
_OBSERVATIONS = frozenset(
    {
        "name_conflict",
        "unclear_mapping",
        "possible_truncation",
        "possible_nucleic_acid",
        "cross_block_join",
        "unsupported_content",
    }
)


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    data: Json | None
    problem: str | None
    model_version: str
    raw_text: str = ""


class LocatorModel(Protocol):
    prompt_version: str

    def answer(
        self, payload: Json, *, previous: str | None = None, repair: str | None = None
    ) -> ModelAnswer: ...


@dataclass(frozen=True, slots=True)
class Assisted:
    result: Json
    model_version: str | None
    prompt_version: str | None


def needs_model(detected_type: str, rule_result: Json) -> bool:
    """Only ask when the rules leave something open; clean files stay deterministic."""
    if detected_type == "fasta":
        return False
    if rule_result["coverage"]["unresolved_blocks"]:
        return True
    return any(r["association_status"] != "unambiguous" for r in rule_result["records"])


def candidates(document: Json, rule_result: Json, file_name: str) -> tuple[list[Json], list[Json]]:
    """Numbered span candidates (S1...) and name candidates (N1...) with exact offsets."""
    spans: list[Json] = []
    seen: set[tuple[str, int, int]] = set()

    def add_span(block_id: str, start: int, end: int) -> None:
        if (block_id, start, end) not in seen:
            seen.add((block_id, start, end))
            spans.append(
                {"id": f"S{len(spans) + 1}", "block_id": block_id, "start": start, "end": end}
            )

    for record in rule_result["records"]:
        for span in record["sequence_spans"]:
            add_span(span["block_id"], span["start"], span["end"])
    for block in document["blocks"]:
        raw = block["raw_text"]
        if is_sequence_like(raw):
            add_span(block["block_id"], 0, len(raw))
        else:
            for match in _RESIDUE_RUN.finditer(raw):
                if is_sequence_like(match.group()):
                    add_span(block["block_id"], match.start(), match.end())

    names: list[Json] = []
    named: set[tuple[str | None, int, int, str]] = set()

    def add_name(value: str, source: str, evidence: Json | None) -> None:
        key = (
            None if evidence is None else evidence["block_id"],
            0 if evidence is None else evidence["start"],
            0 if evidence is None else evidence["end"],
            value,
        )
        if value and key not in named:
            named.add(key)
            names.append(
                {"id": f"N{len(names) + 1}", "value": value, "source": source, "evidence": evidence}
            )

    for record in rule_result["records"]:
        for name in record["names"]:
            add_name(name["value"], name["source"], name["evidence"])
    for block in document["blocks"]:
        raw = block["raw_text"]
        stripped = raw.strip()
        if stripped and "\n" not in stripped and len(stripped) <= 120 and not is_sequence_like(raw):
            start = raw.index(stripped)
            source = "table_cell" if block["type"] == "table_cell" else "heading"
            add_name(
                stripped,
                source,
                {"block_id": block["block_id"], "start": start, "end": start + len(stripped)},
            )
    stem = PurePath(file_name).stem.strip()
    add_name(stem, "filename", None)
    return spans, names


def payload(
    document: Json, rule_result: Json, file_name: str
) -> tuple[Json, list[Json], list[Json]]:
    spans, names = candidates(document, rule_result, file_name)
    by_span = {(s["block_id"], s["start"], s["end"]): s["id"] for s in spans}
    by_name = {
        (n["value"], n["source"], None if n["evidence"] is None else n["evidence"]["block_id"]): n[
            "id"
        ]
        for n in names
    }
    blocks = []
    for block in document["blocks"]:
        raw = block["raw_text"]
        entry: Json = {
            "block_id": block["block_id"],
            "type": block["type"],
            "location": block["location"],
        }
        if len(raw) > SUMMARY_LIMIT:
            entry |= {
                "length": len(raw),
                "summary": raw[:120] + "…",
                "sequence_like": is_sequence_like(raw),
            }
        else:
            entry["text"] = raw
        blocks.append(entry)
    hints = [
        {
            "span_ids": [
                by_span[(s["block_id"], s["start"], s["end"])]
                for s in sorted(r["sequence_spans"], key=lambda s: s["order"])
            ],
            "name_ids": [
                by_name[
                    (
                        n["value"],
                        n["source"],
                        None if n["evidence"] is None else n["evidence"]["block_id"],
                    )
                ]
                for n in r["names"]
            ],
            "association_status": r["association_status"],
        }
        for r in rule_result["records"]
    ]
    request = {
        "file_name": file_name,
        "blocks": blocks,
        "span_candidates": [
            {
                "id": s["id"],
                "block_id": s["block_id"],
                "start": s["start"],
                "end": s["end"],
                "preview": _preview(document, s),
            }
            for s in spans
        ],
        "name_candidates": [
            {
                "id": n["id"],
                "value": n["value"],
                "source": n["source"],
                "block_id": None if n["evidence"] is None else n["evidence"]["block_id"],
            }
            for n in names
        ],
        "rule_grouping": hints,
    }
    return request, spans, names


def _preview(document: Json, span: Json) -> str:
    raw = next(b["raw_text"] for b in document["blocks"] if b["block_id"] == span["block_id"])
    text = raw[span["start"] : span["end"]]
    return text if len(text) <= 60 else f"{text[:30]}…{text[-20:]} ({len(text)} chars)"


def resolve(
    answer: Json, document: Json, rule_result: Json, spans: list[Json], names: list[Json]
) -> tuple[Json | None, str | None]:
    """Turn an ID answer into an extraction result, or explain why it cannot be used.

    Every detected span stays accounted for whatever the model says (design section 4):
    a span no record covers, and a block the rules could not resolve that the answer
    leaves untouched, are reported as unresolved, so QC flags the run for review."""
    span_by_id = {s["id"]: s for s in spans}
    name_by_id = {n["id"]: n for n in names}
    blocks = {b["block_id"]: b["raw_text"] for b in document["blocks"]}
    problems: list[str] = []
    used: set[str] = set()
    records: list[Json] = []
    for index, item in enumerate(answer.get("records", [])):
        span_ids = list(item.get("span_ids", []))
        name_ids = list(item.get("name_ids", []))
        unknown = [i for i in span_ids if i not in span_by_id] + [
            i for i in name_ids if i not in name_by_id
        ]
        if unknown:
            problems.append(f"record {index}: unknown ids {unknown}")
            continue
        reused = [i for i in span_ids if i in used]
        if reused:
            problems.append(f"record {index}: spans {reused} are already used by another record")
        used.update(span_ids)
        status = item.get("association_status")
        if status not in {"unambiguous", "ambiguous", "conflicting"}:
            problems.append(f"record {index}: invalid association_status {status!r}")
            continue
        molecule = item.get("molecule_type")
        if molecule not in {"protein", "nucleic_acid", "uncertain"}:
            problems.append(f"record {index}: invalid molecule_type {molecule!r}")
            continue
        observations = []
        for observation in item.get("observations", []):
            if observation.get("kind") not in _OBSERVATIONS:
                problems.append(f"record {index}: invalid observation kind")
                continue
            observations.append(
                {
                    "kind": observation["kind"],
                    "message": str(observation.get("message") or observation["kind"])[:500],
                    "evidence": [
                        {"block_id": b, "start": 0, "end": len(blocks[b])}
                        for b in observation.get("block_ids", [])
                        if b in blocks
                    ],
                }
            )
        records.append(
            {
                "names": [
                    {k: name_by_id[i][k] for k in ("value", "source", "evidence")} for i in name_ids
                ],
                "molecule_type": molecule,
                "sequence_spans": [
                    {
                        "block_id": span_by_id[i]["block_id"],
                        "start": span_by_id[i]["start"],
                        "end": span_by_id[i]["end"],
                        "order": order,
                    }
                    for order, i in enumerate(span_ids, start=1)
                ],
                "association_status": status,
                "observations": observations,
            }
        )
    unresolved = [b for b in answer.get("unresolved_block_ids", []) if b in blocks]
    if problems:
        return None, "; ".join(problems)
    claimed = [span_by_id[i] for i in used]
    missed = [
        s
        for s in spans
        if not any(
            c["block_id"] == s["block_id"] and c["start"] < s["end"] and s["start"] < c["end"]
            for c in claimed
        )
    ]
    claimed_blocks = {c["block_id"] for c in claimed}
    rules_open = set(rule_result["coverage"]["unresolved_blocks"]) - claimed_blocks
    coverage = dict(document["coverage"])
    coverage["unresolved_blocks"] = sorted(
        set(coverage["unresolved_blocks"])
        | set(unresolved)
        | {s["block_id"] for s in missed}
        | rules_open,
        key=list(blocks).index,
    )
    if missed:
        coverage["warnings"] = [
            *coverage.get("warnings", []),
            f"{len(missed)} detected sequence(s) were not assigned to any record; "
            "check the original.",
        ]
    result = {
        "schema_version": "1.0",
        "file_id": document["file_id"],
        "run_id": document["run_id"],
        "records": records,
        "coverage": coverage,
    }
    cross = check_extraction(blocks, records_from_extraction(result))
    if cross:
        return None, "; ".join(cross)
    return result, None


def assist(
    model: LocatorModel,
    document: Json,
    rule_result: Json,
    file_name: str,
    schema_errors: Callable[[str, Any], list[str]],
) -> Assisted:
    """Ask once, repair once, otherwise keep the rule result with a coverage warning."""
    request, spans, names = payload(document, rule_result, file_name)
    answer = model.answer(request)
    result, problem = (
        (None, answer.problem)
        if answer.data is None
        else resolve(answer.data, document, rule_result, spans, names)
    )
    if result is None and answer.problem not in {"refusal", "unavailable"}:
        repaired = model.answer(
            request,
            previous=answer.raw_text,
            repair=f"The previous answer could not be used: {problem}. "
            "Answer again using only the listed ids.",
        )
        result, problem = (
            (None, repaired.problem)
            if repaired.data is None
            else resolve(repaired.data, document, rule_result, spans, names)
        )
        answer = repaired
    if result is not None and not schema_errors("extraction-result", result):
        return Assisted(result, answer.model_version, model.prompt_version)
    fallback = dict(rule_result)
    coverage = dict(fallback["coverage"])
    coverage["warnings"] = [
        *coverage.get("warnings", []),
        f"Model assistance was not used ({problem}); rule-based results shown.",
    ]
    fallback["coverage"] = coverage
    return Assisted(fallback, None, None)
