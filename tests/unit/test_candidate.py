from dataclasses import replace

import pytest

from sequence_vault.domain.candidate import (
    Candidate,
    CandidateError,
    CandidateStatus,
    InvalidTransition,
    ResolutionNotAllowed,
    RevisionConflict,
    UnresolvedIssues,
)
from sequence_vault.domain.extraction import Name
from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    QcResult,
    evaluate_spans,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

BLOCKS = {"h1": "RSPO3_C07", "p1": "MKTAYIAKQR", "p2": "MKXAYIAKQR"}
NAME = Name("RSPO3_C07", "fasta_header", BlockSpan("h1", 0, 9))
CONTEXT = ExtractionContext(1, "unambiguous", frozenset(), MoleculeType.PROTEIN, False)


def qc_for(registry: QcRegistry, block_id: str) -> QcResult:
    return evaluate_spans(registry, BLOCKS, [SequenceSpan(block_id, 0, 10, 1)], CONTEXT)


def in_review(registry: QcRegistry, block_id: str = "p1") -> Candidate:
    draft = Candidate.extracted("c1", "run1", (NAME,), (SequenceSpan(block_id, 0, 10, 1),))
    return draft.validated(qc_for(registry, block_id), parser_delimited=True)


def test_validation_moves_a_clean_draft_to_review_as_complete(registry: QcRegistry) -> None:
    candidate = in_review(registry)
    assert (candidate.status, candidate.revision, candidate.completeness) == (
        CandidateStatus.NEEDS_REVIEW,
        1,
        "complete",
    )


def test_name_without_sequence_waits_for_content(registry: QcRegistry) -> None:
    draft = Candidate.extracted("c1", "run1", (NAME,), ())
    qc = evaluate_spans(registry, BLOCKS, [], CONTEXT)
    pending = draft.validated(qc, parser_delimited=False)
    assert pending.status is CandidateStatus.PENDING_CONTENT
    assert pending.archive(1).status is CandidateStatus.ARCHIVED


def test_approval_needs_every_review_issue_resolved(registry: QcRegistry) -> None:
    candidate = in_review(registry, "p2")  # X raises QC04 (REVIEW)
    with pytest.raises(UnresolvedIssues, match="QC04"):
        candidate.approve(1, "reviewer")
    resolved = candidate.resolve(1, registry, "QC04", "confirm_residue_semantics")
    approved = resolved.approve(1, "reviewer")
    assert (approved.status, approved.approved_revision) == (CandidateStatus.APPROVED, 1)


def test_resolutions_must_come_from_the_rule_allowlist(registry: QcRegistry) -> None:
    candidate = in_review(registry, "p2")
    with pytest.raises(ResolutionNotAllowed, match="not allowed"):
        candidate.resolve(1, registry, "QC04", "ignore")


def test_block_issues_cannot_be_resolved_away(registry: QcRegistry) -> None:
    blocked = Candidate.extracted("c1", "run1", (NAME,), (SequenceSpan("p1", 0, 99, 1),))
    qc = evaluate_spans(registry, BLOCKS, list(blocked.spans), CONTEXT)
    blocked = blocked.validated(qc, parser_delimited=False)
    assert blocked.status is CandidateStatus.BLOCKED
    fixed = blocked.revise_sequence(
        1,
        qc_for(registry, "p1"),
        reason="Span ran past the block",
        spans=(SequenceSpan("p1", 0, 10, 1),),
    )
    assert (fixed.status, fixed.revision, fixed.origin) == (
        CandidateStatus.NEEDS_REVIEW,
        2,
        "manual_revision",
    )


def test_edits_void_approval_and_stale_revisions_conflict(registry: QcRegistry) -> None:
    approved = in_review(registry).approve(1, "reviewer")
    renamed = approved.rename(1, Name("RSPO3 C07", "manual", None))
    assert (renamed.status, renamed.revision, renamed.approved_revision) == (
        CandidateStatus.NEEDS_REVIEW,
        2,
        None,
    )
    with pytest.raises(RevisionConflict):
        renamed.approve(1, "reviewer")


def test_typed_sequence_edits_need_a_reason(registry: QcRegistry) -> None:
    candidate = in_review(registry)
    typed_qc = evaluate_typed(registry, "MKTAYIAKQW", CONTEXT)
    with pytest.raises(CandidateError, match="reason"):
        candidate.revise_sequence(1, typed_qc, reason=" ", typed_sequence="MKTAYIAKQW")
    edited = candidate.revise_sequence(
        1, typed_qc, reason="Source scan shows W", typed_sequence="MKTAYIAKQW"
    )
    assert (edited.typed_sequence, edited.completeness) == ("MKTAYIAKQW", "unknown")


def test_commit_requires_the_approved_revision(registry: QcRegistry) -> None:
    approved = in_review(registry).approve(1, "reviewer")
    assert approved.mark_committed(1).status is CandidateStatus.COMMITTED
    with pytest.raises(InvalidTransition):
        in_review(registry).mark_committed(1)


def test_reextraction_supersedes_open_candidates_only(registry: QcRegistry) -> None:
    assert in_review(registry).supersede().status is CandidateStatus.SUPERSEDED
    committed = in_review(registry).approve(1, "reviewer").mark_committed(1)
    with pytest.raises(InvalidTransition):
        committed.supersede()


def test_rename_can_carry_refreshed_publication_issues(registry: QcRegistry) -> None:
    candidate = in_review(registry)
    assert candidate.qc is not None
    qc09 = registry.issue("QC09", "This name already has version 1 with a different sequence.")
    refreshed = replace(candidate.qc, issues=(*candidate.qc.issues, qc09))
    renamed = candidate.rename(1, Name("Existing", "manual", None), refreshed)
    assert renamed.qc is refreshed
    with pytest.raises(UnresolvedIssues, match="QC09"):
        renamed.approve(2, "reviewer")
