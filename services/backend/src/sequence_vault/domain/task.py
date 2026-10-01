"""File task lifecycle (design section 3)."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum

from sequence_vault.domain.candidate import CandidateStatus


class TaskStatus(StrEnum):
    UPLOADED = "UPLOADED"
    SCANNING = "SCANNING"
    PARSING = "PARSING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    REVIEW_READY = "REVIEW_READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"


PIPELINE = (
    TaskStatus.UPLOADED,
    TaskStatus.SCANNING,
    TaskStatus.PARSING,
    TaskStatus.EXTRACTING,
    TaskStatus.VALIDATING,
    TaskStatus.REVIEW_READY,
)
TERMINAL = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.UNSUPPORTED}
)
SETTLED_CANDIDATES = frozenset(
    {CandidateStatus.COMMITTED, CandidateStatus.REJECTED, CandidateStatus.ARCHIVED}
)


class TaskError(Exception):
    pass


class StaleStage(TaskError):
    """Another worker already moved the task on; drop the duplicate delivery."""


class ItemsPending(TaskError):
    pass


@dataclass(frozen=True, slots=True)
class FileTask:
    task_id: str
    status: TaskStatus = TaskStatus.UPLOADED
    failure_code: str | None = None

    def advance(self, finished_stage: TaskStatus) -> "FileTask":
        """Move past ``finished_stage``. A mismatch means a duplicate or late delivery."""
        if self.status is not finished_stage:
            raise StaleStage(f"Task is {self.status}, not {finished_stage}.")
        if finished_stage is TaskStatus.REVIEW_READY:
            raise TaskError("Review-ready tasks complete through complete().")
        return replace(self, status=PIPELINE[PIPELINE.index(finished_stage) + 1])

    def mark_unsupported(self) -> "FileTask":
        if self.status is not TaskStatus.SCANNING:
            raise TaskError("Format support is decided while scanning.")
        return replace(self, status=TaskStatus.UNSUPPORTED)

    def fail(self, failure_code: str) -> "FileTask":
        self._require_open()
        return replace(self, status=TaskStatus.FAILED, failure_code=failure_code)

    def cancel(self) -> "FileTask":
        self._require_open()
        return replace(self, status=TaskStatus.CANCELLED)

    def complete(self, candidate_statuses: Iterable[CandidateStatus]) -> "FileTask":
        """Complete only when every current-run candidate is committed, rejected or archived."""
        if self.status is not TaskStatus.REVIEW_READY:
            raise TaskError(f"Only review-ready tasks complete, not {self.status}.")
        pending = [status for status in candidate_statuses if status not in SETTLED_CANDIDATES]
        if pending:
            raise ItemsPending(f"{len(pending)} candidate(s) still need a decision.")
        return replace(self, status=TaskStatus.COMPLETED)

    def _require_open(self) -> None:
        if self.status in TERMINAL:
            raise TaskError(f"Task is already {self.status}.")
