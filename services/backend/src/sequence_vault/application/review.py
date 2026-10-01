"""Review use cases: rename, revise, resolve, approve, reject, archive (design section 7)."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

from sequence_vault.application.authorization import Action, Actor, authorize
from sequence_vault.application.contract_mapping import context_for, records_from_extraction
from sequence_vault.application.errors import Conflict, InvalidRequest, NotFound
from sequence_vault.application.ports import CandidateRow, UnitOfWork, UnitOfWorkFactory
from sequence_vault.domain.candidate import (
    Candidate,
    CandidateError,
    InvalidTransition,
    ResolutionNotAllowed,
    RevisionConflict,
    UnresolvedIssues,
)
from sequence_vault.domain.extraction import Name
from sequence_vault.domain.naming import name_key
from sequence_vault.domain.publication import plan_publication, sequence_sha256
from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    QcResult,
    evaluate_spans,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.domain.spans import SequenceSpan
from sequence_vault.domain.task import ItemsPending, TaskStatus

PUBLICATION_RULES = frozenset({"QC09", "QC10"})


@contextmanager
def domain_errors() -> Iterator[None]:
    """Translate domain rule violations into application errors."""
    try:
        yield
    except RevisionConflict as error:
        raise Conflict(str(error), code="revision_conflict") from error
    except UnresolvedIssues as error:
        raise Conflict(str(error), code="unresolved_issues") from error
    except InvalidTransition as error:
        raise Conflict(str(error), code="invalid_state") from error
    except ResolutionNotAllowed as error:
        raise InvalidRequest(str(error), code="resolution_not_allowed") from error
    except CandidateError as error:
        raise InvalidRequest(str(error)) from error


def load_candidate(
    uow: UnitOfWork, actor: Actor, candidate_id: str, action: Action
) -> CandidateRow:
    row = uow.candidates.get(candidate_id, for_update=True)
    if row is None or row.tenant_id != actor.tenant_id:
        raise NotFound("Candidate not found.")
    authorize(uow.members.roles(actor.user_id, row.project_id), action)
    task = uow.tasks.get_by_file(row.file_id)
    if task is not None and task.task.status is TaskStatus.CANCELLED:
        raise Conflict("The task was cancelled.", code="task_cancelled")
    return row


def qc_inputs(
    uow: UnitOfWork, row: CandidateRow, *, fragment: bool = False
) -> tuple[dict[str, str], ExtractionContext]:
    """Blocks and QC context for re-running QC on a stored candidate."""
    run = uow.runs.get(row.candidate.run_id)
    if run is None:
        raise NotFound("Extraction run not found.")
    blocks = uow.runs.blocks(run.run_id)
    document: dict[str, Any] = {
        "blocks": [
            {
                "block_id": b.block_id,
                "type": b.type,
                "raw_text": b.raw_text,
                "extraction_method": b.extraction_method,
            }
            for b in blocks
        ],
        "coverage": run.coverage or {"unresolved_blocks": [], "truncated": False},
    }
    if row.extraction_record_index is not None and run.extraction_result is not None:
        record = records_from_extraction(run.extraction_result)[row.extraction_record_index]
        context = context_for(record, document)
    else:
        context = ExtractionContext(
            name_count=max(1, len(row.candidate.extracted_names)),
            association_status="unambiguous",
            observation_kinds=frozenset(),
            molecule_type_hint=MoleculeType.PROTEIN,
            coverage_risk=False,
        )
    return {b.block_id: b.raw_text for b in blocks}, replace(context, declared_fragment=fragment)


def with_publication_issues(
    uow: UnitOfWork, registry: QcRegistry, row: CandidateRow, name: Name | None, qc: QcResult
) -> QcResult:
    """Replace QC09/QC10 with a fresh preview limited to the candidate's own project."""
    issues = tuple(issue for issue in qc.issues if issue.rule_id not in PUBLICATION_RULES)
    sequence = qc.normalized.sequence if qc.normalized else ""
    if not sequence or name is None or qc.blocked:
        return replace(qc, issues=issues)
    project = row.project_id
    visible = uow.publication.find_entities_in_project(
        project, MoleculeType.PROTEIN.value, sequence_sha256(sequence)
    )
    record = uow.publication.find_record(project, name_key(name.value))
    plan = plan_publication(registry, sequence, visible, record, None)
    return replace(qc, issues=issues + plan.issues)


def settle_task(uow: UnitOfWork, file_id: str) -> None:
    """Complete a review-ready task once every current-run candidate is settled."""
    task_row = uow.tasks.get_by_file(file_id, for_update=True)
    if task_row is None or task_row.task.status is not TaskStatus.REVIEW_READY:
        return
    if task_row.current_run_id is None:
        return
    statuses = [r.candidate.status for r in uow.candidates.list_for_run(task_row.current_run_id)]
    try:
        completed = task_row.task.complete(statuses)
    except ItemsPending:
        return
    uow.tasks.save(replace(task_row, task=completed))


def _finish(
    uow: UnitOfWork,
    actor: Actor,
    row: CandidateRow,
    updated: Candidate,
    event: str,
    detail: dict[str, Any] | None = None,
) -> CandidateRow:
    uow.candidates.save(updated)
    uow.audit.record(
        actor.tenant_id,
        actor.user_id,
        event,
        "candidate",
        updated.candidate_id,
        {"revision": updated.revision, "status": updated.status.value, **(detail or {})},
    )
    return replace(row, candidate=updated)


class ReviewService:
    def __init__(self, uow_factory: UnitOfWorkFactory, registry: QcRegistry) -> None:
        self.uow_factory = uow_factory
        self.registry = registry

    def rename(self, actor: Actor, candidate_id: str, revision: int, value: str) -> CandidateRow:
        value = value.strip()
        if not value:
            raise InvalidRequest("A name cannot be blank.")
        with self.uow_factory() as uow:
            row = load_candidate(uow, actor, candidate_id, Action.EDIT)
            current = row.candidate
            # Choosing an extracted name keeps its source and evidence.
            name = next((n for n in current.extracted_names if n.value == value), None)
            name = name or Name(value, "manual", None)
            qc = (
                None
                if current.qc is None
                else with_publication_issues(uow, self.registry, row, name, current.qc)
            )
            with domain_errors():
                updated = current.rename(revision, name, qc)
            row = _finish(uow, actor, row, updated, "candidate.renamed", {"name": value})
            uow.commit()
            return row

    def revise_sequence(
        self,
        actor: Actor,
        candidate_id: str,
        revision: int,
        *,
        reason: str,
        spans: tuple[SequenceSpan, ...] = (),
        typed_sequence: str | None = None,
        fragment: bool = False,
    ) -> CandidateRow:
        with self.uow_factory() as uow:
            row = load_candidate(uow, actor, candidate_id, Action.EDIT)
            blocks, context = qc_inputs(uow, row, fragment=fragment)
            if typed_sequence is not None:
                qc = evaluate_typed(self.registry, typed_sequence, context)
            else:
                qc = evaluate_spans(self.registry, blocks, spans, context)
            qc = with_publication_issues(uow, self.registry, row, row.candidate.name, qc)
            with domain_errors():
                updated = row.candidate.revise_sequence(
                    revision,
                    qc,
                    reason=reason,
                    spans=spans,
                    typed_sequence=typed_sequence,
                    fragment=fragment,
                )
            row = _finish(
                uow,
                actor,
                row,
                updated,
                "candidate.sequence_revised",
                {"reason": reason, "typed": typed_sequence is not None, "fragment": fragment},
            )
            uow.commit()
            return row

    def resolve(
        self, actor: Actor, candidate_id: str, revision: int, rule_id: str, resolution: str
    ) -> CandidateRow:
        with self.uow_factory() as uow:
            row = load_candidate(uow, actor, candidate_id, Action.REVIEW)
            with domain_errors():
                updated = row.candidate.resolve(revision, self.registry, rule_id, resolution)
            row = _finish(
                uow,
                actor,
                row,
                updated,
                "candidate.issue_resolved",
                {"rule_id": rule_id, "resolution": resolution},
            )
            uow.commit()
            return row

    def decide(self, actor: Actor, candidate_id: str, revision: int, approve: bool) -> CandidateRow:
        with self.uow_factory() as uow:
            row = load_candidate(uow, actor, candidate_id, Action.REVIEW)
            with domain_errors():
                if approve:
                    updated = row.candidate.approve(revision, actor.user_id)
                else:
                    updated = row.candidate.reject(revision)
            decision = "approved" if approve else "rejected"
            uow.reviews.add(candidate_id, updated.run_id, revision, decision, actor.user_id)
            row = _finish(uow, actor, row, updated, f"candidate.{decision}")
            settle_task(uow, row.file_id)
            uow.commit()
            return row

    def archive(self, actor: Actor, candidate_id: str, revision: int) -> CandidateRow:
        with self.uow_factory() as uow:
            row = load_candidate(uow, actor, candidate_id, Action.EDIT)
            with domain_errors():
                updated = row.candidate.archive(revision)
            row = _finish(uow, actor, row, updated, "candidate.archived")
            settle_task(uow, row.file_id)
            uow.commit()
            return row
