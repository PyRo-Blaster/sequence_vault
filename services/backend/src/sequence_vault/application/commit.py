"""Per-item commit transaction (design section 7, "Commit Transaction")."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sequence_vault.application.authorization import PERMISSIONS, Action, Actor
from sequence_vault.application.ports import (
    CandidateRow,
    ConcurrentUpdate,
    StoredCommit,
    UnitOfWork,
    UnitOfWorkFactory,
)
from sequence_vault.application.review import settle_task
from sequence_vault.domain.candidate import CandidateStatus, RevisionConflict
from sequence_vault.domain.naming import name_key
from sequence_vault.domain.publication import (
    RecordAction,
    StoredEntity,
    StoredRecord,
    plan_publication,
    sequence_sha256,
)
from sequence_vault.domain.qc.engine import MoleculeType
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.domain.task import TaskStatus

PUBLISHED_TYPE = MoleculeType.PROTEIN.value


class CommitStatus(StrEnum):
    COMMITTED = "COMMITTED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CommitItem:
    candidate_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    candidate_id: str
    status: CommitStatus
    reason: str | None = None
    record_id: str | None = None
    record_version_id: str | None = None


@dataclass(frozen=True, slots=True)
class CommitPreview:
    """What committing one candidate would write now. ``record_action`` is None when the
    candidate cannot be committed (not visible, no name or no sequence)."""

    candidate_id: str
    record_action: RecordAction | None
    reuses_sequence: bool = False


class _Stop(Exception):
    def __init__(self, status: CommitStatus, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class CommitService:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, registry: QcRegistry, *, max_residues: int
    ) -> None:
        self.uow_factory = uow_factory
        self.registry = registry
        self.max_residues = max_residues

    def commit(self, actor: Actor, key: str, items: Sequence[CommitItem]) -> list[CommitOutcome]:
        """Commit each item in its own transaction; one failure never affects another item."""
        return [self._commit_with_retry(actor, key, item) for item in items]

    def preview(self, actor: Actor, candidate_ids: Sequence[str]) -> list[CommitPreview]:
        """Plan each commit as ``commit`` would, in order, without writing. Earlier items of
        the batch count as published, so two new candidates with one name or one sequence
        preview as they will commit."""
        names: dict[tuple[str, str], str] = {}
        sequences: set[tuple[str, str]] = set()
        previews = []
        with self.uow_factory() as uow:
            for candidate_id in candidate_ids:
                row = uow.candidates.get(candidate_id)
                qc = None if row is None else row.candidate.qc
                if (
                    row is None
                    or row.tenant_id != actor.tenant_id
                    or not uow.members.roles(actor.user_id, row.project_id)
                    or row.candidate.name is None
                    or qc is None
                    or qc.normalized is None
                    or not qc.normalized.sequence
                ):
                    previews.append(CommitPreview(candidate_id, None))
                    continue
                sequence = qc.normalized.sequence
                key_name = name_key(row.candidate.name.value)
                record = uow.publication.find_record(row.project_id, key_name)
                if record is None and (row.project_id, key_name) in names:
                    record = StoredRecord("", 1, names[(row.project_id, key_name)])
                matches = list(
                    uow.publication.find_entities(
                        row.tenant_id, PUBLISHED_TYPE, sequence_sha256(sequence)
                    )
                )
                if (row.tenant_id, sequence) in sequences:
                    matches.append(StoredEntity("", sequence))
                plan = plan_publication(
                    self.registry,
                    sequence,
                    matches,
                    record,
                    row.candidate.resolutions.get("QC09"),
                )
                if plan.record_action in (RecordAction.CREATE_RECORD, RecordAction.NEW_VERSION):
                    names[(row.project_id, key_name)] = sequence
                sequences.add((row.tenant_id, sequence))
                previews.append(
                    CommitPreview(
                        candidate_id, plan.record_action, plan.reuse_entity_id is not None
                    )
                )
        return previews

    def _commit_with_retry(self, actor: Actor, key: str, item: CommitItem) -> CommitOutcome:
        for attempt in range(2):
            try:
                return self._commit_one(actor, key, item)
            except ConcurrentUpdate:
                if attempt == 1:
                    return CommitOutcome(
                        item.candidate_id, CommitStatus.CONFLICT, "concurrent_change"
                    )
        raise AssertionError("unreachable")

    def _commit_one(self, actor: Actor, key: str, item: CommitItem) -> CommitOutcome:
        with self.uow_factory() as uow:
            try:
                outcome = self._apply(uow, actor, key, item)
            except _Stop as stop:
                return CommitOutcome(item.candidate_id, stop.status, stop.reason)
            if outcome.status is CommitStatus.COMMITTED:
                uow.commit()
            return outcome

    def _apply(self, uow: UnitOfWork, actor: Actor, key: str, item: CommitItem) -> CommitOutcome:
        # Authorize first: a replayed key must not reveal a result to someone who could
        # not commit the candidate now.
        row = uow.candidates.get(item.candidate_id, for_update=True)
        if row is None or row.tenant_id != actor.tenant_id:
            raise _Stop(CommitStatus.FAILED, "not_found")
        roles = uow.members.roles(actor.user_id, row.project_id)
        if not roles:
            raise _Stop(CommitStatus.FAILED, "not_found")
        if not roles & PERMISSIONS[Action.COMMIT]:
            raise _Stop(CommitStatus.FAILED, "forbidden")

        stored = uow.commits.get(key, item.candidate_id)
        if stored is not None:
            if stored.approved_revision != item.revision:
                raise _Stop(CommitStatus.CONFLICT, "idempotency_key_reused")
            return CommitOutcome(
                item.candidate_id,
                CommitStatus(stored.status),
                record_id=stored.record_id,
                record_version_id=stored.record_version_id,
            )

        candidate = row.candidate
        if candidate.status is CandidateStatus.COMMITTED:
            return CommitOutcome(item.candidate_id, CommitStatus.ALREADY_COMMITTED)

        source = uow.files.get(row.file_id)
        if source is None or source.security_status != "clean":
            raise _Stop(CommitStatus.FAILED, "file_not_clean")
        task = uow.tasks.get_by_file(row.file_id, for_update=True)
        if task is None or task.task.status is TaskStatus.CANCELLED:
            raise _Stop(CommitStatus.CONFLICT, "task_cancelled")
        if task.current_run_id != candidate.run_id:
            raise _Stop(CommitStatus.CONFLICT, "superseded_run")
        if (
            candidate.status is not CandidateStatus.APPROVED
            or candidate.approved_revision != item.revision
            or candidate.revision != item.revision
        ):
            raise _Stop(CommitStatus.CONFLICT, "stale_revision")
        qc = candidate.qc
        if qc is None or qc.qc_version != self.registry.version:
            raise _Stop(CommitStatus.CONFLICT, "qc_version_changed")
        if qc.blocked or qc.normalized is None or not qc.normalized.sequence:
            raise _Stop(CommitStatus.CONFLICT, "blocking_issues")
        if len(qc.normalized.sequence) > self.max_residues:
            # Every path to publication ends here, whatever created the candidate.
            raise _Stop(CommitStatus.FAILED, "sequence_limit")
        protein_confirmed = candidate.resolutions.get("QC11") == "confirm_molecule_type"
        if qc.molecule_type is not MoleculeType.PROTEIN and not protein_confirmed:
            raise _Stop(CommitStatus.CONFLICT, "not_protein")
        if candidate.name is None:
            raise _Stop(CommitStatus.CONFLICT, "name_missing")

        return self._publish(uow, actor, key, item, row, qc.normalized.sequence)

    def _publish(
        self,
        uow: UnitOfWork,
        actor: Actor,
        key: str,
        item: CommitItem,
        row: CandidateRow,
        sequence: str,
    ) -> CommitOutcome:
        candidate = row.candidate
        assert candidate.name is not None
        publication = uow.publication
        key_name = name_key(candidate.name.value)
        record = publication.find_record(row.project_id, key_name, for_update=True)
        matches = publication.find_entities(
            row.tenant_id, PUBLISHED_TYPE, sequence_sha256(sequence)
        )
        plan = plan_publication(
            self.registry, sequence, matches, record, candidate.resolutions.get("QC09")
        )
        if plan.record_action is RecordAction.NEEDS_DECISION:
            raise _Stop(CommitStatus.CONFLICT, "needs_version_decision")
        if plan.record_action is RecordAction.CANCEL:
            raise _Stop(CommitStatus.CONFLICT, "version_cancelled")
        if matches and plan.reuse_entity_id is None:
            raise _Stop(CommitStatus.FAILED, "hash_collision")

        entity_id = plan.reuse_entity_id or publication.create_entity(
            row.tenant_id, PUBLISHED_TYPE, sequence
        )
        if record is None:
            record_id = publication.create_record(
                row.tenant_id, row.project_id, key_name, candidate.name.value
            )
            version_id = publication.add_version(record_id, 1, entity_id, None, actor.user_id)
        else:
            record_id = record.record_id
            current = publication.current_version(record_id)
            assert current is not None
            if plan.record_action is RecordAction.ADD_PROVENANCE:
                version_id = current.version_id
            else:
                publication.supersede(current.version_id)
                version_id = publication.add_version(
                    record_id, current.version_no + 1, entity_id, current.version_id, actor.user_id
                )
        publication.add_provenance(version_id, row, actor.user_id)

        try:
            committed = candidate.mark_committed(item.revision)
        except RevisionConflict as error:
            raise _Stop(CommitStatus.CONFLICT, "stale_revision") from error
        uow.candidates.save(committed)
        uow.commits.put(
            key,
            item.candidate_id,
            StoredCommit(item.revision, CommitStatus.COMMITTED.value, record_id, version_id),
        )
        uow.audit.record(
            row.tenant_id,
            actor.user_id,
            "candidate.committed",
            "candidate",
            item.candidate_id,
            {
                "revision": item.revision,
                "record_id": record_id,
                "record_version_id": version_id,
                "action": plan.record_action.value,
                "reused_entity": plan.reuse_entity_id is not None,
            },
        )
        settle_task(uow, row.file_id)
        return CommitOutcome(
            item.candidate_id,
            CommitStatus.COMMITTED,
            record_id=record_id,
            record_version_id=version_id,
        )
