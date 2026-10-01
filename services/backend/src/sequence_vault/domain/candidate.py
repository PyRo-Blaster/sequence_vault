"""Candidate lifecycle: revisions, issue resolutions, approval and commitment."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from sequence_vault.domain.extraction import Name
from sequence_vault.domain.qc.engine import QcResult
from sequence_vault.domain.qc.registry import QcRegistry, Severity
from sequence_vault.domain.spans import SequenceSpan


class CandidateStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"
    APPROVED = "APPROVED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    PENDING_CONTENT = "PENDING_CONTENT"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"


TERMINAL = frozenset(
    {
        CandidateStatus.COMMITTED,
        CandidateStatus.REJECTED,
        CandidateStatus.ARCHIVED,
        CandidateStatus.SUPERSEDED,
    }
)
EDITABLE = frozenset(
    {
        CandidateStatus.NEEDS_REVIEW,
        CandidateStatus.BLOCKED,
        CandidateStatus.APPROVED,
        CandidateStatus.PENDING_CONTENT,
    }
)


class CandidateError(Exception):
    """Base class for rejected candidate operations."""


class RevisionConflict(CandidateError):
    """The caller acted on an older revision (HTTP 409)."""


class InvalidTransition(CandidateError):
    pass


class ResolutionNotAllowed(CandidateError):
    pass


class UnresolvedIssues(CandidateError):
    pass


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    run_id: str
    revision: int
    status: CandidateStatus
    name: Name | None
    extracted_names: tuple[Name, ...]
    spans: tuple[SequenceSpan, ...]
    typed_sequence: str | None
    completeness: str
    origin: str
    qc: QcResult | None
    resolutions: Mapping[str, str] = field(default_factory=dict)
    approved_revision: int | None = None
    approved_by: str | None = None

    @classmethod
    def extracted(
        cls,
        candidate_id: str,
        run_id: str,
        names: tuple[Name, ...],
        spans: tuple[SequenceSpan, ...],
    ) -> "Candidate":
        """A new DRAFT. A single name is preselected; several names wait for the reviewer."""
        return cls(
            candidate_id=candidate_id,
            run_id=run_id,
            revision=1,
            status=CandidateStatus.DRAFT,
            name=names[0] if len(names) == 1 else None,
            extracted_names=names,
            spans=spans,
            typed_sequence=None,
            completeness="unknown",
            origin="extracted",
            qc=None,
        )

    def validated(self, qc: QcResult, *, parser_delimited: bool) -> "Candidate":
        """Leave DRAFT after QC. ``parser_delimited`` means every span is a whole sequence
        block delimited by the parser (a FASTA body), the only case treated as complete."""
        self._require(CandidateStatus.DRAFT)
        complete = parser_delimited and "QC05" not in qc.rule_ids(Severity.BLOCK)
        return replace(
            self,
            qc=qc,
            completeness="complete" if complete else "unknown",
            status=self._status_after_qc(qc, has_sequence=bool(self.spans)),
        )

    def rename(self, expected_revision: int, name: Name) -> "Candidate":
        self._check_editable(expected_revision)
        return self._next_revision(name=name)

    def revise_sequence(
        self,
        expected_revision: int,
        qc: QcResult,
        *,
        reason: str,
        spans: tuple[SequenceSpan, ...] = (),
        typed_sequence: str | None = None,
        fragment: bool = False,
    ) -> "Candidate":
        """Replace the evidence spans, or type a sequence by hand. Both need a reason."""
        self._check_editable(expected_revision)
        if not reason.strip():
            raise CandidateError("A sequence change needs a reason.")
        if bool(spans) == (typed_sequence is not None):
            raise CandidateError("Provide either evidence spans or a typed sequence.")
        return self._next_revision(
            spans=spans,
            typed_sequence=typed_sequence,
            qc=qc,
            completeness="fragment" if fragment else "unknown",
            origin="manual_revision",
            status=self._status_after_qc(qc, has_sequence=True),
        )

    def resolve(
        self, expected_revision: int, registry: QcRegistry, rule_id: str, resolution: str
    ) -> "Candidate":
        """Record a reviewer decision for a REVIEW or INFO issue on this revision."""
        self._check_revision(expected_revision)
        if self.status is not CandidateStatus.NEEDS_REVIEW or self.qc is None:
            raise InvalidTransition(f"Issues can only be resolved in review, not {self.status}.")
        if rule_id not in {issue.rule_id for issue in self.qc.issues}:
            raise ResolutionNotAllowed(f"{rule_id} is not an issue on revision {self.revision}.")
        rule = registry.rules[rule_id]
        if rule.severity is Severity.BLOCK:
            raise ResolutionNotAllowed(f"{rule_id} blocks; change the candidate to clear it.")
        if resolution not in rule.allowed_resolutions:
            raise ResolutionNotAllowed(f"{resolution!r} is not allowed for {rule_id}.")
        return replace(self, resolutions={**self.resolutions, rule_id: resolution})

    def approve(self, expected_revision: int, reviewer_id: str) -> "Candidate":
        self._check_revision(expected_revision)
        self._require(CandidateStatus.NEEDS_REVIEW)
        assert self.qc is not None
        unresolved = sorted(self.qc.rule_ids(Severity.REVIEW) - self.resolutions.keys())
        if unresolved:
            raise UnresolvedIssues(f"Resolve before approving: {', '.join(unresolved)}")
        if self.name is None:
            raise UnresolvedIssues("Select a name before approving.")
        return replace(
            self,
            status=CandidateStatus.APPROVED,
            approved_revision=self.revision,
            approved_by=reviewer_id,
        )

    def reject(self, expected_revision: int) -> "Candidate":
        self._check_editable(expected_revision)
        return replace(self, status=CandidateStatus.REJECTED)

    def archive(self, expected_revision: int) -> "Candidate":
        self._check_revision(expected_revision)
        self._require(CandidateStatus.PENDING_CONTENT)
        return replace(self, status=CandidateStatus.ARCHIVED)

    def supersede(self) -> "Candidate":
        """Called for every open candidate of an older run when a file is re-extracted."""
        if self.status in TERMINAL:
            raise InvalidTransition(f"{self.status} candidates cannot be superseded.")
        return replace(self, status=CandidateStatus.SUPERSEDED)

    def mark_committed(self, approved_revision: int) -> "Candidate":
        """Only inside the commit transaction, after every recheck has passed."""
        self._require(CandidateStatus.APPROVED)
        if not approved_revision == self.approved_revision == self.revision:
            raise RevisionConflict("The approval does not match the current revision.")
        return replace(self, status=CandidateStatus.COMMITTED)

    @staticmethod
    def _status_after_qc(qc: QcResult, *, has_sequence: bool) -> CandidateStatus:
        if not has_sequence:
            return CandidateStatus.PENDING_CONTENT
        return CandidateStatus.BLOCKED if qc.blocked else CandidateStatus.NEEDS_REVIEW

    def _next_revision(self, **changes: object) -> "Candidate":
        """Every edit bumps the revision and voids approval and resolutions."""
        updated = replace(
            self,
            revision=self.revision + 1,
            resolutions={},
            approved_revision=None,
            approved_by=None,
            **changes,  # type: ignore[arg-type]
        )
        if "status" in changes or updated.qc is None:
            return updated
        has_sequence = bool(updated.spans) or updated.typed_sequence is not None
        return replace(updated, status=self._status_after_qc(updated.qc, has_sequence=has_sequence))

    def _check_editable(self, expected_revision: int) -> None:
        self._check_revision(expected_revision)
        if self.status not in EDITABLE:
            raise InvalidTransition(f"{self.status} candidates cannot be changed.")

    def _check_revision(self, expected_revision: int) -> None:
        if expected_revision != self.revision:
            raise RevisionConflict(
                f"Revision {expected_revision} is stale; the current revision is {self.revision}."
            )

    def _require(self, status: CandidateStatus) -> None:
        if self.status is not status:
            raise InvalidTransition(f"Expected {status}, found {self.status}.")
