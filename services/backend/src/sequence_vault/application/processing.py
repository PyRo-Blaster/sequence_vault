"""Pipeline stages: scan, parse, extract, validate (design sections 3-6).

Slow work runs outside transactions. Each stage then re-reads the task with FOR UPDATE and
only proceeds if the task is still in this stage and generation, so duplicate or late
deliveries and cancelled tasks never change anything.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from sequence_vault.application.authorization import Action, Actor, authorize
from sequence_vault.application.contract_mapping import (
    context_for,
    parser_delimited,
    records_from_extraction,
)
from sequence_vault.application.errors import Conflict, LimitExceeded, NotFound
from sequence_vault.application.ports import (
    CandidateRow,
    DocumentParser,
    Job,
    Json,
    ObjectStore,
    ParseFailed,
    RunRow,
    Scanner,
    TaskRow,
    TypeDetector,
    UnitOfWork,
    UnitOfWorkFactory,
)
from sequence_vault.application.review import with_publication_issues
from sequence_vault.application.rule_extraction import extract
from sequence_vault.domain.candidate import TERMINAL, Candidate
from sequence_vault.domain.extraction import check_extraction
from sequence_vault.domain.qc.engine import evaluate_spans
from sequence_vault.domain.qc.registry import QcRegistry
from sequence_vault.domain.task import TaskError, TaskStatus

SchemaCheck = Callable[[str, Any], list[str]]


@dataclass(frozen=True, slots=True)
class PipelineLimits:
    max_candidates: int
    max_residues: int


class Pipeline:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        store: ObjectStore,
        scanner: Scanner,
        detector: TypeDetector,
        parser: DocumentParser,
        registry: QcRegistry,
        enabled_formats: frozenset[str],
        schema_errors: SchemaCheck,
        limits: PipelineLimits,
    ) -> None:
        self.uow_factory = uow_factory
        self.store = store
        self.scanner = scanner
        self.detector = detector
        self.parser = parser
        self.registry = registry
        self.enabled_formats = enabled_formats
        self.schema_errors = schema_errors
        self.limits = limits

    # -- dispatch -------------------------------------------------------------------------

    def handle(self, job: Job) -> None:
        handlers = {
            TaskStatus.SCANNING.value: self.scan,
            TaskStatus.PARSING.value: self.parse,
            TaskStatus.EXTRACTING.value: self.extract,
            TaskStatus.VALIDATING.value: self.validate,
        }
        handlers[job.stage](job)

    def give_up(self, job: Job, failure_code: str) -> None:
        """Fail the task after retries are exhausted or an unexpected error."""
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            if row is None:
                return
            if job.stage == TaskStatus.SCANNING.value:
                uow.files.set_security(row.file_id, "scan_failed", None)
            self._fail(uow, row, failure_code)
            uow.commit()

    # -- helpers --------------------------------------------------------------------------

    def _current(self, uow: UnitOfWork, job: Job) -> TaskRow | None:
        row = uow.tasks.get(job.task_id, for_update=True)
        if row is None or row.generation != job.generation or row.task.status.value != job.stage:
            return None
        return row

    def _fail(self, uow: UnitOfWork, row: TaskRow, code: str) -> None:
        uow.tasks.save(replace(row, task=row.task.fail(code)))
        source = uow.files.get(row.file_id)
        if source is not None:
            uow.audit.record(
                source.tenant_id, None, "task.failed", "task", row.task.task_id, {"code": code}
            )

    def _advance(self, uow: UnitOfWork, row: TaskRow, **changes: Any) -> TaskRow:
        advanced = replace(row, task=row.task.advance(row.task.status), **changes)
        uow.tasks.save(advanced)
        if advanced.task.status is not TaskStatus.REVIEW_READY:
            uow.jobs.enqueue(advanced.task.task_id, advanced.generation, advanced.task.status.value)
        return advanced

    def _document(self, uow: UnitOfWork, run: RunRow) -> Json:
        return {
            "file_id": run.file_id,
            "run_id": run.run_id,
            "blocks": [
                {
                    "block_id": b.block_id,
                    "type": b.type,
                    "raw_text": b.raw_text,
                    "location": b.location,
                    "extraction_method": b.extraction_method,
                }
                for b in uow.runs.blocks(run.run_id)
            ],
            "coverage": run.coverage or {"unresolved_blocks": [], "truncated": False},
        }

    # -- stages ---------------------------------------------------------------------------

    def scan(self, job: Job) -> None:
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            source = None if row is None else uow.files.get(row.file_id)
        if row is None or source is None:
            return
        data = self.store.get(source.object_key)
        verdict = self.scanner.scan(data)
        detection = self.detector.detect(data, source.original_name)
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            if row is None:
                return
            if not verdict.clean:
                uow.files.set_security(source.file_id, "infected", None)
                self._fail(uow, row, "infected")
            elif detection.format is None or detection.format not in self.enabled_formats:
                uow.files.set_security(source.file_id, "clean", detection.format)
                uow.tasks.save(
                    replace(
                        row,
                        task=row.task.mark_unsupported(),
                    )
                )
                uow.audit.record(
                    source.tenant_id,
                    None,
                    "task.unsupported",
                    "task",
                    row.task.task_id,
                    {"reason": detection.reason},
                )
            else:
                uow.files.set_security(source.file_id, "clean", detection.format)
                self._advance(uow, row)
            uow.commit()

    def parse(self, job: Job) -> None:
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            source = None if row is None else uow.files.get(row.file_id)
        if row is None or source is None or source.detected_type is None:
            return
        run_id = f"run_{uuid.uuid4().hex}"
        options: Json = {"tracked_changes_view": "not_applicable"}
        failure: str | None = None
        document: Json = {}
        try:
            document = self.parser.parse(
                source.detected_type,
                self.store.get(source.object_key),
                file_id=source.file_id,
                run_id=run_id,
                parse_options=options,
            )
            if self.schema_errors("document-ir", document):
                failure = "invalid_document_ir"
        except ParseFailed as error:
            failure = error.code
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            if row is None:
                return
            if failure is not None:
                self._fail(uow, row, failure)
            else:
                uow.runs.create(
                    RunRow(
                        run_id=run_id,
                        file_id=source.file_id,
                        generation=row.generation,
                        qc_version=self.registry.version,
                        schema_version="1.0",
                        parser_version=document["parser_version"],
                        model_version=None,
                        prompt_version=None,
                        coverage=document["coverage"],
                        extraction_result=None,
                    ),
                    parse_options=document["parse_options"],
                    source_encoding=document["source_encoding"],
                )
                uow.runs.add_blocks(run_id, document["blocks"])
                self._advance(uow, row, current_run_id=run_id)
            uow.commit()

    def extract(self, job: Job) -> None:
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            if row is None or row.current_run_id is None:
                return
            run = uow.runs.get(row.current_run_id)
            source = uow.files.get(row.file_id)
            assert run is not None and source is not None
            document = self._document(uow, run)
            failure: str | None = None
            try:
                result = extract(
                    document,
                    source.original_name,
                    max_candidates=self.limits.max_candidates,
                    max_residues=self.limits.max_residues,
                )
            except LimitExceeded as error:
                failure, result = error.code, {}
            if failure is None and self.schema_errors("extraction-result", result):
                failure = "invalid_extraction_result"
            if failure is None:
                blocks = {b["block_id"]: b["raw_text"] for b in document["blocks"]}
                if check_extraction(blocks, records_from_extraction(result)):
                    failure = "invalid_extraction_result"
            if failure is not None:
                self._fail(uow, row, failure)
            else:
                uow.runs.set_extraction(run.run_id, result, model_version=None, prompt_version=None)
                self._advance(uow, row)
            uow.commit()

    def validate(self, job: Job) -> None:
        with self.uow_factory() as uow:
            row = self._current(uow, job)
            if row is None or row.current_run_id is None:
                return
            run = uow.runs.get(row.current_run_id)
            source = uow.files.get(row.file_id)
            assert run is not None and source is not None and run.extraction_result is not None
            document = self._document(uow, run)
            blocks = {b["block_id"]: b["raw_text"] for b in document["blocks"]}
            for index, record in enumerate(records_from_extraction(run.extraction_result)):
                candidate = Candidate.extracted(
                    f"cand_{uuid.uuid4().hex}", run.run_id, record.names, record.spans
                )
                candidate_row = CandidateRow(
                    candidate, source.tenant_id, source.project_id, source.file_id, index
                )
                qc = evaluate_spans(
                    self.registry, blocks, record.spans, context_for(record, document)
                )
                qc = with_publication_issues(uow, self.registry, candidate_row, candidate.name, qc)
                validated = candidate.validated(
                    qc, parser_delimited=parser_delimited(record, document)
                )
                uow.candidates.add(replace(candidate_row, candidate=validated))
            self._advance(uow, row)
            uow.audit.record(
                source.tenant_id,
                None,
                "task.review_ready",
                "task",
                row.task.task_id,
                {"run_id": run.run_id},
            )
            uow.commit()


class TaskService:
    """User actions on tasks: cancel and reprocess."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory

    def _task(self, uow: UnitOfWork, actor: Actor, task_id: str) -> TaskRow:
        row = uow.tasks.get(task_id, for_update=True)
        source = None if row is None else uow.files.get(row.file_id)
        if row is None or source is None or source.tenant_id != actor.tenant_id:
            raise NotFound("Task not found.")
        authorize(uow.members.roles(actor.user_id, source.project_id), Action.EDIT)
        return row

    def cancel(self, actor: Actor, task_id: str) -> TaskRow:
        with self.uow_factory() as uow:
            row = self._task(uow, actor, task_id)
            try:
                cancelled = replace(row, task=row.task.cancel())
            except TaskError as error:
                raise Conflict(str(error), code="invalid_state") from error
            uow.tasks.save(cancelled)
            uow.audit.record(actor.tenant_id, actor.user_id, "task.cancelled", "task", task_id)
            uow.commit()
            return cancelled

    def reprocess(self, actor: Actor, task_id: str) -> TaskRow:
        """New extraction run; open candidates of the old run are superseded (T16)."""
        with self.uow_factory() as uow:
            row = self._task(uow, actor, task_id)
            source = uow.files.get(row.file_id)
            if source is None or source.security_status != "clean":
                raise Conflict("Only clean files can be reprocessed.", code="file_not_clean")
            try:
                task = row.task.reprocess()
            except TaskError as error:
                raise Conflict(str(error), code="invalid_state") from error
            if row.current_run_id is not None:
                for candidate_row in uow.candidates.list_for_run(row.current_run_id):
                    if candidate_row.candidate.status not in TERMINAL:
                        uow.candidates.save(candidate_row.candidate.supersede())
            updated = replace(row, task=task, generation=row.generation + 1)
            uow.tasks.save(updated)
            uow.jobs.enqueue(task_id, updated.generation, TaskStatus.PARSING.value)
            uow.audit.record(
                actor.tenant_id,
                actor.user_id,
                "task.reprocessed",
                "task",
                task_id,
                {"generation": updated.generation},
            )
            uow.commit()
            return updated
