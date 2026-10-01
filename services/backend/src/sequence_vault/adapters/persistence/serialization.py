"""Lossless JSON for domain objects stored in jsonb columns."""

from typing import Any

from sequence_vault.domain.candidate import Candidate, CandidateStatus
from sequence_vault.domain.extraction import Name
from sequence_vault.domain.normalization import Normalized, Transformation
from sequence_vault.domain.qc.engine import MoleculeType, QcResult
from sequence_vault.domain.qc.registry import Issue, Severity
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

Json = dict[str, Any]


def span_to_json(span: BlockSpan) -> Json:
    return {"block_id": span.block_id, "start": span.start, "end": span.end}


def span_from_json(data: Json) -> BlockSpan:
    return BlockSpan(data["block_id"], data["start"], data["end"])


def name_to_json(name: Name) -> Json:
    evidence = None if name.evidence is None else span_to_json(name.evidence)
    return {"value": name.value, "source": name.source, "evidence": evidence}


def name_from_json(data: Json) -> Name:
    evidence = None if data["evidence"] is None else span_from_json(data["evidence"])
    return Name(data["value"], data["source"], evidence)


def sequence_span_to_json(span: SequenceSpan) -> Json:
    return {"block_id": span.block_id, "start": span.start, "end": span.end, "order": span.order}


def sequence_span_from_json(data: Json) -> SequenceSpan:
    return SequenceSpan(data["block_id"], data["start"], data["end"], data["order"])


def issue_to_json(issue: Issue) -> Json:
    return {
        "rule_id": issue.rule_id,
        "severity": issue.severity.value,
        "message": issue.message,
        "evidence": [span_to_json(span) for span in issue.evidence],
    }


def issue_from_json(data: Json) -> Issue:
    return Issue(
        data["rule_id"],
        Severity(data["severity"]),
        data["message"],
        tuple(span_from_json(span) for span in data["evidence"]),
    )


def transformation_to_json(change: Transformation) -> Json:
    return {
        "rule_id": change.rule_id,
        "operation": change.operation,
        "reason": change.reason,
        "positions": list(change.positions),
    }


def qc_to_json(qc: QcResult) -> Json:
    normalized = None
    if qc.normalized is not None:
        normalized = {
            "sequence": qc.normalized.sequence,
            "raw_positions": list(qc.normalized.raw_positions),
            "transformations": [transformation_to_json(t) for t in qc.normalized.transformations],
        }
    return {
        "qc_version": qc.qc_version,
        "raw_text": qc.raw_text,
        "normalized": normalized,
        "molecule_type": qc.molecule_type.value,
        "issues": [issue_to_json(issue) for issue in qc.issues],
    }


def qc_from_json(data: Json) -> QcResult:
    normalized = None
    if data["normalized"] is not None:
        n = data["normalized"]
        normalized = Normalized(
            n["sequence"],
            tuple(n["raw_positions"]),
            tuple(
                Transformation(t["rule_id"], t["operation"], t["reason"], tuple(t["positions"]))
                for t in n["transformations"]
            ),
        )
    return QcResult(
        data["qc_version"],
        data["raw_text"],
        normalized,
        MoleculeType(data["molecule_type"]),
        tuple(issue_from_json(issue) for issue in data["issues"]),
    )


def candidate_to_json(candidate: Candidate) -> Json:
    return {
        "candidate_id": candidate.candidate_id,
        "run_id": candidate.run_id,
        "revision": candidate.revision,
        "status": candidate.status.value,
        "name": None if candidate.name is None else name_to_json(candidate.name),
        "extracted_names": [name_to_json(name) for name in candidate.extracted_names],
        "spans": [sequence_span_to_json(span) for span in candidate.spans],
        "typed_sequence": candidate.typed_sequence,
        "completeness": candidate.completeness,
        "origin": candidate.origin,
        "qc": None if candidate.qc is None else qc_to_json(candidate.qc),
        "resolutions": dict(candidate.resolutions),
        "approved_revision": candidate.approved_revision,
        "approved_by": candidate.approved_by,
    }


def candidate_from_json(data: Json) -> Candidate:
    return Candidate(
        candidate_id=data["candidate_id"],
        run_id=data["run_id"],
        revision=data["revision"],
        status=CandidateStatus(data["status"]),
        name=None if data["name"] is None else name_from_json(data["name"]),
        extracted_names=tuple(name_from_json(name) for name in data["extracted_names"]),
        spans=tuple(sequence_span_from_json(span) for span in data["spans"]),
        typed_sequence=data["typed_sequence"],
        completeness=data["completeness"],
        origin=data["origin"],
        qc=None if data["qc"] is None else qc_from_json(data["qc"]),
        resolutions=dict(data["resolutions"]),
        approved_revision=data["approved_revision"],
        approved_by=data["approved_by"],
    )
