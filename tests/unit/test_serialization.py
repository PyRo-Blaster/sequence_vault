import json

from sequence_vault.adapters.persistence.serialization import (
    candidate_from_json,
    candidate_to_json,
)
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.extraction import Name
from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    evaluate_spans,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

BLOCKS = {"h1": "RSPO3", "p1": "mkt 1 a…yX*"}
CONTEXT = ExtractionContext(
    2, "conflicting", frozenset({"name_conflict"}), MoleculeType.PROTEIN, True
)
NAMES = (Name("RSPO3", "fasta_header", BlockSpan("h1", 0, 5)), Name("RSPO3_v2", "filename", None))


def round_trip(candidate: Candidate) -> Candidate:
    return candidate_from_json(json.loads(json.dumps(candidate_to_json(candidate))))


def test_blocked_candidate_with_every_issue_kind_round_trips(registry: QcRegistry) -> None:
    spans = (SequenceSpan("p1", 0, 11, 1),)
    qc = evaluate_spans(registry, BLOCKS, spans, CONTEXT)
    candidate = Candidate.extracted("c1", "r1", NAMES, spans).validated(qc, parser_delimited=False)
    assert len(qc.issues) >= 6
    assert round_trip(candidate) == candidate


def test_typed_approved_and_pending_candidates_round_trip(registry: QcRegistry) -> None:
    clean = ExtractionContext(1, "unambiguous", frozenset(), MoleculeType.PROTEIN, False)
    spans = (SequenceSpan("h1", 0, 5, 1),)
    qc = evaluate_spans(registry, {"h1": "MKTAY"}, spans, clean)
    base = Candidate.extracted("c1", "r1", NAMES[:1], spans).validated(qc, parser_delimited=True)
    typed = base.revise_sequence(
        1, evaluate_typed(registry, "MKTAW", clean), reason="fix", typed_sequence="MKTAW"
    )
    approved = typed.approve(2, "u1")
    pending = Candidate.extracted("c2", "r1", NAMES[:1], ()).validated(
        evaluate_spans(registry, {}, [], clean), parser_delimited=False
    )
    for candidate in (typed, approved, pending):
        assert round_trip(candidate) == candidate
