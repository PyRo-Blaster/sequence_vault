import pytest

from sequence_vault.domain.candidate import CandidateStatus
from sequence_vault.domain.task import FileTask, ItemsPending, StaleStage, TaskError, TaskStatus


def test_advances_one_stage_at_a_time() -> None:
    task = FileTask("t1")
    for stage in (TaskStatus.UPLOADED, TaskStatus.SCANNING, TaskStatus.PARSING):
        task = task.advance(stage)
    assert task.status is TaskStatus.EXTRACTING


def test_duplicate_delivery_is_detected() -> None:
    task = FileTask("t1").advance(TaskStatus.UPLOADED)
    with pytest.raises(StaleStage):
        task.advance(TaskStatus.UPLOADED)


def test_completes_only_when_every_candidate_is_settled() -> None:
    task = FileTask("t1", status=TaskStatus.REVIEW_READY)
    with pytest.raises(ItemsPending, match="1 candidate"):
        task.complete([CandidateStatus.COMMITTED, CandidateStatus.PENDING_CONTENT])
    done = task.complete([CandidateStatus.COMMITTED, CandidateStatus.ARCHIVED])
    assert done.status is TaskStatus.COMPLETED


def test_terminal_tasks_cannot_be_cancelled_or_failed() -> None:
    cancelled = FileTask("t1").cancel()
    with pytest.raises(TaskError):
        cancelled.fail("parser_crash")


def test_unsupported_is_decided_while_scanning() -> None:
    scanning = FileTask("t1", status=TaskStatus.SCANNING)
    assert scanning.mark_unsupported().status is TaskStatus.UNSUPPORTED
    with pytest.raises(TaskError):
        FileTask("t1").mark_unsupported()
