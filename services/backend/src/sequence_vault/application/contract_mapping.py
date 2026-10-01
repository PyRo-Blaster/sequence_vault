"""Translate between the JSON contracts in packages/contracts and domain objects.

Input documents must already have passed JSON Schema validation.
"""

from collections.abc import Mapping
from typing import Any

from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.extraction import ExtractedRecord, Name
from sequence_vault.domain.qc.engine import ExtractionContext, MoleculeType
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

Json = Mapping[str, Any]


def blocks_from_document_ir(document: Json) -> dict[str, str]:
    return {block["block_id"]: block["raw_text"] for block in document["blocks"]}


def records_from_extraction(result: Json) -> tuple[ExtractedRecord, ...]:
    return tuple(
        ExtractedRecord(
            names=tuple(_name(item) for item in record["names"]),
            molecule_type_hint=MoleculeType(record["molecule_type"]),
            spans=tuple(
                SequenceSpan(span["block_id"], span["start"], span["end"], span["order"])
                for span in record["sequence_spans"]
            ),
            association_status=record["association_status"],
            observation_kinds=frozenset(item["kind"] for item in record["observations"]),
        )
        for record in result["records"]
    )


def context_for(record: ExtractedRecord, document: Json) -> ExtractionContext:
    coverage = document["coverage"]
    methods = {block["block_id"]: block["extraction_method"] for block in document["blocks"]}
    coverage_risk = (
        bool(coverage["unresolved_blocks"])
        or coverage["truncated"]
        or bool(coverage.get("warnings"))
        or any(methods[span.block_id] != "text_parser" for span in record.spans)
    )
    return ExtractionContext(
        name_count=len(record.names),
        association_status=record.association_status,
        observation_kinds=record.observation_kinds,
        molecule_type_hint=record.molecule_type_hint,
        coverage_risk=coverage_risk,
    )


def parser_delimited(record: ExtractedRecord, document: Json) -> bool:
    """True when every span covers a whole parser-delimited sequence block."""
    blocks = {block["block_id"]: block for block in document["blocks"]}
    return bool(record.spans) and all(
        blocks[span.block_id]["type"] == "sequence"
        and span.start == 0
        and span.end == len(blocks[span.block_id]["raw_text"])
        for span in record.spans
    )


def candidate_to_wire(candidate: Candidate, extraction_record_index: int | None) -> dict[str, Any]:
    qc = candidate.qc
    if qc is None:
        raise ValueError("Only validated candidates have a wire representation.")
    wire: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": candidate.candidate_id,
        "run_id": candidate.run_id,
    }
    if extraction_record_index is not None:
        wire["extraction_record_index"] = extraction_record_index
    wire |= {
        "revision": candidate.revision,
        "name": _name_to_wire(candidate.name) if candidate.name else None,
        "extracted_names": [_name_to_wire(name) for name in candidate.extracted_names],
        "sequence_spans": [
            {"block_id": s.block_id, "start": s.start, "end": s.end, "order": s.order}
            for s in candidate.spans
        ],
        "raw_text": qc.raw_text,
        "normalized_sequence": qc.normalized.sequence if qc.normalized else "",
        "molecule_type": qc.molecule_type.value,
        "completeness": candidate.completeness,
        "status": candidate.status.value,
        "origin": candidate.origin,
        "transformation_log": [
            {
                "rule_id": change.rule_id,
                "operation": change.operation,
                "reason": change.reason,
                "positions": list(change.positions),
            }
            for change in (qc.normalized.transformations if qc.normalized else ())
        ],
        "issues": [
            {
                "rule_id": issue.rule_id,
                "severity": issue.severity.value,
                "message": issue.message,
                "evidence": [_span_to_wire(span) for span in issue.evidence],
            }
            for issue in qc.issues
        ],
        "qc_version": qc.qc_version,
    }
    return wire


def _name(item: Json) -> Name:
    evidence = item["evidence"]
    span = None if evidence is None else BlockSpan(**evidence)
    return Name(item["value"], item["source"], span)


def _name_to_wire(name: Name) -> dict[str, Any]:
    evidence = None if name.evidence is None else _span_to_wire(name.evidence)
    return {"value": name.value, "source": name.source, "evidence": evidence}


def _span_to_wire(span: BlockSpan) -> dict[str, Any]:
    return {"block_id": span.block_id, "start": span.start, "end": span.end}
