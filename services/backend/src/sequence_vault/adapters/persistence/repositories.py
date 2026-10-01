"""SQLAlchemy Core implementations of the application ports."""

import uuid
from types import TracebackType
from typing import Any, Self

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.adapters.persistence.serialization import (
    candidate_from_json,
    candidate_to_json,
    sequence_span_to_json,
    transformation_to_json,
)
from sequence_vault.application.authorization import Role
from sequence_vault.application.ports import (
    BlockRow,
    CandidateRow,
    ConcurrentUpdate,
    CurrentVersion,
    FileRow,
    Json,
    RunRow,
    StoredCommit,
    TaskRow,
)
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.publication import StoredEntity, StoredRecord, sequence_sha256
from sequence_vault.domain.task import FileTask, TaskStatus


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _conflicts(connection: Connection, statement: Any) -> Any:
    """Run a statement whose failure means another transaction won a race."""
    try:
        with connection.begin_nested():
            return connection.execute(statement)
    except (IntegrityError, OperationalError) as error:
        raise ConcurrentUpdate(str(error.orig)) from error


class SqlMembers:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def roles(self, user_id: str, project_id: str) -> frozenset[Role]:
        rows = self.c.execute(
            select(t.project_member.c.role).where(
                t.project_member.c.user_id == user_id, t.project_member.c.project_id == project_id
            )
        )
        return frozenset(Role(role) for (role,) in rows)

    def projects(self, user_id: str) -> list[tuple[str, str, frozenset[Role]]]:
        rows = self.c.execute(
            select(t.project.c.id, t.project.c.name, t.project_member.c.role)
            .join(t.project_member, t.project_member.c.project_id == t.project.c.id)
            .where(t.project_member.c.user_id == user_id)
            .order_by(t.project.c.name)
        )
        found: dict[str, tuple[str, set[Role]]] = {}
        for project_id, name, role in rows:
            found.setdefault(project_id, (name, set()))[1].add(Role(role))
        return [(pid, name, frozenset(roles)) for pid, (name, roles) in found.items()]


class SqlCandidates:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def _row(self, row: Any) -> CandidateRow:
        return CandidateRow(
            candidate=candidate_from_json(row.body),
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            file_id=row.file_id,
            extraction_record_index=row.extraction_record_index,
        )

    def get(self, candidate_id: str, *, for_update: bool = False) -> CandidateRow | None:
        query = select(t.candidate).where(t.candidate.c.id == candidate_id)
        if for_update:
            query = query.with_for_update()
        row = self.c.execute(query).first()
        return None if row is None else self._row(row)

    def add(self, row: CandidateRow) -> None:
        candidate = row.candidate
        self.c.execute(
            insert(t.candidate).values(
                id=candidate.candidate_id,
                run_id=candidate.run_id,
                file_id=row.file_id,
                project_id=row.project_id,
                tenant_id=row.tenant_id,
                extraction_record_index=row.extraction_record_index,
                revision=candidate.revision,
                status=candidate.status.value,
                body=candidate_to_json(candidate),
            )
        )

    def save(self, candidate: Candidate) -> None:
        self.c.execute(
            update(t.candidate)
            .where(t.candidate.c.id == candidate.candidate_id)
            .values(
                revision=candidate.revision,
                status=candidate.status.value,
                body=candidate_to_json(candidate),
                updated_at=func.now(),
            )
        )

    def list_for_run(self, run_id: str) -> list[CandidateRow]:
        rows = self.c.execute(
            select(t.candidate)
            .where(t.candidate.c.run_id == run_id)
            .order_by(t.candidate.c.extraction_record_index, t.candidate.c.created_at)
        )
        return [self._row(row) for row in rows]


class SqlFiles:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def get(self, file_id: str) -> FileRow | None:
        row = self.c.execute(select(t.source_file).where(t.source_file.c.id == file_id)).first()
        if row is None:
            return None
        return FileRow(
            file_id=row.id,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            uploaded_by=row.uploaded_by,
            original_name=row.original_name,
            declared_bytes=row.declared_bytes,
            declared_sha256=row.declared_sha256,
            byte_count=row.byte_count,
            sha256=row.sha256,
            object_key=row.object_key,
            detected_type=row.detected_type,
            security_status=row.security_status,
        )

    def create(self, row: FileRow) -> None:
        self.c.execute(
            insert(t.source_file).values(
                id=row.file_id,
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                uploaded_by=row.uploaded_by,
                original_name=row.original_name,
                declared_bytes=row.declared_bytes,
                declared_sha256=row.declared_sha256,
                object_key=row.object_key,
                security_status=row.security_status,
            )
        )

    def mark_uploaded(self, file_id: str, byte_count: int, sha256: str) -> None:
        self.c.execute(
            update(t.source_file)
            .where(t.source_file.c.id == file_id)
            .values(byte_count=byte_count, sha256=sha256, security_status="uploaded")
        )

    def set_security(self, file_id: str, status: str, detected_type: str | None) -> None:
        self.c.execute(
            update(t.source_file)
            .where(t.source_file.c.id == file_id)
            .values(security_status=status, detected_type=detected_type)
        )


class SqlTasks:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def get(self, task_id: str, *, for_update: bool = False) -> TaskRow | None:
        return self._one(t.file_task.c.id == task_id, for_update)

    def get_by_file(self, file_id: str, *, for_update: bool = False) -> TaskRow | None:
        return self._one(t.file_task.c.file_id == file_id, for_update)

    def create(self, row: TaskRow) -> None:
        _conflicts(
            self.c,
            insert(t.file_task).values(
                id=row.task.task_id,
                file_id=row.file_id,
                status=row.task.status.value,
                failure_code=row.task.failure_code,
                current_run_id=row.current_run_id,
                generation=row.generation,
            ),
        )

    def _one(self, condition: Any, for_update: bool) -> TaskRow | None:
        query = select(t.file_task).where(condition)
        if for_update:
            query = query.with_for_update()
        row = self.c.execute(query).first()
        if row is None:
            return None
        return TaskRow(
            task=FileTask(row.id, TaskStatus(row.status), row.failure_code),
            file_id=row.file_id,
            current_run_id=row.current_run_id,
            generation=row.generation,
        )

    def save(self, row: TaskRow) -> None:
        self.c.execute(
            update(t.file_task)
            .where(t.file_task.c.id == row.task.task_id)
            .values(
                status=row.task.status.value,
                failure_code=row.task.failure_code,
                current_run_id=row.current_run_id,
                generation=row.generation,
                updated_at=func.now(),
            )
        )


class SqlRuns:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def get(self, run_id: str) -> RunRow | None:
        row = self.c.execute(
            select(t.extraction_run).where(t.extraction_run.c.id == run_id)
        ).first()
        if row is None:
            return None
        return RunRow(
            run_id=row.id,
            file_id=row.file_id,
            generation=row.generation,
            qc_version=row.qc_version,
            schema_version=row.schema_version,
            parser_version=row.parser_version,
            model_version=row.model_version,
            prompt_version=row.prompt_version,
            coverage=row.coverage,
            extraction_result=row.extraction_result,
        )

    def blocks(self, run_id: str) -> list[BlockRow]:
        rows = self.c.execute(
            select(t.document_block)
            .where(t.document_block.c.run_id == run_id)
            .order_by(t.document_block.c.position)
        )
        return [
            BlockRow(row.block_id, row.type, row.raw_text, row.location, row.extraction_method)
            for row in rows
        ]

    def create(self, row: RunRow, *, parse_options: Json, source_encoding: str) -> None:
        self.c.execute(
            insert(t.extraction_run).values(
                id=row.run_id,
                file_id=row.file_id,
                generation=row.generation,
                parser_version=row.parser_version,
                model_version=row.model_version,
                prompt_version=row.prompt_version,
                schema_version=row.schema_version,
                qc_version=row.qc_version,
                parse_options=parse_options,
                source_encoding=source_encoding,
                coverage=row.coverage,
                extraction_result=row.extraction_result,
            )
        )

    def add_blocks(self, run_id: str, blocks: list[Json]) -> None:
        if not blocks:
            return
        self.c.execute(
            insert(t.document_block),
            [
                {
                    "run_id": run_id,
                    "block_id": block["block_id"],
                    "position": position,
                    "type": block["type"],
                    "raw_text": block["raw_text"],
                    "location": block["location"],
                    "extraction_method": block["extraction_method"],
                }
                for position, block in enumerate(blocks)
            ],
        )

    def set_extraction(
        self, run_id: str, result: Json, *, model_version: str | None, prompt_version: str | None
    ) -> None:
        self.c.execute(
            update(t.extraction_run)
            .where(t.extraction_run.c.id == run_id)
            .values(
                extraction_result=result,
                coverage=result["coverage"],
                model_version=model_version,
                prompt_version=prompt_version,
            )
        )


class SqlPublication:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def find_entities(self, tenant_id: str, molecule_type: str, sha256: str) -> list[StoredEntity]:
        e = t.sequence_entity
        rows = self.c.execute(
            select(e.c.id, e.c.canonical_sequence).where(
                e.c.tenant_id == tenant_id, e.c.molecule_type == molecule_type, e.c.sha256 == sha256
            )
        )
        return [StoredEntity(row.id, row.canonical_sequence) for row in rows]

    def find_entities_in_project(
        self, project_id: str, molecule_type: str, sha256: str
    ) -> list[StoredEntity]:
        """Only entities this project already publishes, so other projects stay invisible."""
        e, v, r = t.sequence_entity, t.record_version, t.record
        rows = self.c.execute(
            select(e.c.id, e.c.canonical_sequence)
            .distinct()
            .join(v, v.c.sequence_entity_id == e.c.id)
            .join(r, r.c.id == v.c.record_id)
            .where(
                r.c.project_id == project_id,
                e.c.molecule_type == molecule_type,
                e.c.sha256 == sha256,
            )
        )
        return [StoredEntity(row.id, row.canonical_sequence) for row in rows]

    def create_entity(self, tenant_id: str, molecule_type: str, sequence: str) -> str:
        entity_id = new_id("seq")
        _conflicts(
            self.c,
            insert(t.sequence_entity).values(
                id=entity_id,
                tenant_id=tenant_id,
                molecule_type=molecule_type,
                canonical_sequence=sequence,
                length=len(sequence),
                sha256=sequence_sha256(sequence),
            ),
        )
        return entity_id

    def find_record(
        self, project_id: str, name_key: str, *, for_update: bool = False
    ) -> StoredRecord | None:
        query = select(t.record.c.id).where(
            t.record.c.project_id == project_id, t.record.c.name_key == name_key
        )
        if for_update:
            query = query.with_for_update()
        record_id = self.c.execute(query).scalar()
        if record_id is None:
            return None
        current = self.current_version(record_id)
        if current is None:
            return None
        return StoredRecord(record_id, current.version_no, current.sequence)

    def create_record(self, tenant_id: str, project_id: str, name_key: str, display: str) -> str:
        record_id = new_id("rec")
        _conflicts(
            self.c,
            insert(t.record).values(
                id=record_id,
                tenant_id=tenant_id,
                project_id=project_id,
                name_key=name_key,
                display_name=display,
            ),
        )
        return record_id

    def current_version(self, record_id: str) -> CurrentVersion | None:
        v, e = t.record_version, t.sequence_entity
        row = self.c.execute(
            select(v.c.id, v.c.version_no, e.c.canonical_sequence)
            .join(e, e.c.id == v.c.sequence_entity_id)
            .where(v.c.record_id == record_id, v.c.is_current)
        ).first()
        return (
            None if row is None else CurrentVersion(row.id, row.version_no, row.canonical_sequence)
        )

    def supersede(self, version_id: str) -> None:
        self.c.execute(
            update(t.record_version)
            .where(t.record_version.c.id == version_id)
            .values(is_current=False)
        )

    def add_version(
        self,
        record_id: str,
        version_no: int,
        entity_id: str,
        previous_version_id: str | None,
        created_by: str,
    ) -> str:
        version_id = new_id("ver")
        _conflicts(
            self.c,
            insert(t.record_version).values(
                id=version_id,
                record_id=record_id,
                version_no=version_no,
                sequence_entity_id=entity_id,
                previous_version_id=previous_version_id,
                is_current=True,
                created_by=created_by,
            ),
        )
        return version_id

    def add_provenance(self, record_version_id: str, row: CandidateRow, committed_by: str) -> None:
        candidate = row.candidate
        assert candidate.qc is not None and candidate.approved_by is not None
        normalized = candidate.qc.normalized
        self.c.execute(
            insert(t.provenance).values(
                record_version_id=record_version_id,
                candidate_id=candidate.candidate_id,
                candidate_revision=candidate.revision,
                run_id=candidate.run_id,
                file_id=row.file_id,
                approved_by=candidate.approved_by,
                committed_by=committed_by,
                evidence={
                    "spans": [sequence_span_to_json(span) for span in candidate.spans],
                    "typed_sequence": candidate.typed_sequence,
                    "name": None
                    if candidate.name is None
                    else {"value": candidate.name.value, "source": candidate.name.source},
                    "origin": candidate.origin,
                    "completeness": candidate.completeness,
                },
                transformation_log=[]
                if normalized is None
                else [transformation_to_json(c) for c in normalized.transformations],
            )
        )


class SqlReviews:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def add(
        self, candidate_id: str, run_id: str, revision: int, decision: str, reviewer: str
    ) -> None:
        self.c.execute(
            insert(t.review).values(
                candidate_id=candidate_id,
                run_id=run_id,
                revision=revision,
                decision=decision,
                reviewer_id=reviewer,
            )
        )


class SqlAudit:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def record(
        self,
        tenant_id: str,
        actor_id: str | None,
        event: str,
        entity_type: str,
        entity_id: str,
        detail: Json | None = None,
    ) -> None:
        self.c.execute(
            insert(t.audit_event).values(
                tenant_id=tenant_id,
                actor_id=actor_id,
                event=event,
                entity_type=entity_type,
                entity_id=entity_id,
                detail=detail or {},
            )
        )


class SqlCommits:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def get(self, key: str, candidate_id: str) -> StoredCommit | None:
        row = self.c.execute(
            select(t.commit_result).where(
                t.commit_result.c.idempotency_key == key,
                t.commit_result.c.candidate_id == candidate_id,
            )
        ).first()
        if row is None:
            return None
        return StoredCommit(row.approved_revision, row.status, row.record_id, row.record_version_id)

    def put(self, key: str, candidate_id: str, result: StoredCommit) -> None:
        _conflicts(
            self.c,
            insert(t.commit_result).values(
                idempotency_key=key,
                candidate_id=candidate_id,
                approved_revision=result.approved_revision,
                status=result.status,
                record_id=result.record_id,
                record_version_id=result.record_version_id,
            ),
        )


class SqlJobs:
    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def enqueue(self, task_id: str, generation: int, stage: str) -> None:
        self.c.execute(
            pg_insert(t.stage_job)
            .values(task_id=task_id, generation=generation, stage=stage)
            .on_conflict_do_nothing(index_elements=["task_id", "generation", "stage"])
        )


class SqlUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._committed = False

    def __enter__(self) -> Self:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        c = self.connection
        self.members = SqlMembers(c)
        self.candidates = SqlCandidates(c)
        self.files = SqlFiles(c)
        self.tasks = SqlTasks(c)
        self.runs = SqlRuns(c)
        self.publication = SqlPublication(c)
        self.reviews = SqlReviews(c)
        self.audit = SqlAudit(c)
        self.commits = SqlCommits(c)
        self.jobs = SqlJobs(c)
        return self

    def commit(self) -> None:
        try:
            self.transaction.commit()
        except (IntegrityError, OperationalError) as error:
            raise ConcurrentUpdate(str(error.orig)) from error
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._committed and self.transaction.is_active:
            self.transaction.rollback()
        self.connection.close()


class SqlUnitOfWorkFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def __call__(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.engine)
