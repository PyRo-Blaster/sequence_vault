"""Authorized reads for the API: tasks, candidates, evidence, records and exports."""

import re
from typing import Any, Protocol

from sequence_vault.application.authorization import PERMISSIONS, Action, Actor, Role, authorize
from sequence_vault.application.contract_mapping import candidate_to_wire
from sequence_vault.application.errors import InvalidRequest, NotFound
from sequence_vault.application.ports import CandidateRow, ObjectStore, UnitOfWorkFactory
from sequence_vault.domain.normalization import normalize
from sequence_vault.domain.publication import sequence_sha256
from sequence_vault.domain.qc.registry import QcRegistry

Json = dict[str, Any]
MAX_PAGE = 200


class ReadModel(Protocol):
    def user_by_subject(self, subject: str) -> Json | None: ...
    def projects_for_user(self, user_id: str) -> list[Json]: ...
    def task(self, task_id: str) -> Json | None: ...
    def tasks(
        self, project_id: str, limit: int, cursor: list[Any] | None
    ) -> tuple[list[Json], str | None]: ...
    def run(self, run_id: str) -> Json | None: ...
    def records(
        self,
        project_ids: list[str],
        *,
        q: str | None,
        sequence_sha256: str | None,
        min_length: int | None,
        max_length: int | None,
        limit: int,
        cursor: list[Any] | None,
    ) -> tuple[list[Json], str | None]: ...
    def record(self, record_id: str) -> Json | None: ...


Cursor = list[Any] | None


def fasta_header(name: str, record_id: str, version_no: int) -> str:
    """One safe header line: no control characters and no '>' that could start a record."""
    safe = re.sub(r"[\x00-\x1f\x7f>]", " ", name)
    safe = re.sub(r"\s+", "_", safe.strip()) or "unnamed"
    return f">{safe} record={record_id} version={version_no}"


def to_fasta(header: str, sequence: str, width: int = 60) -> str:
    lines = [sequence[i : i + width] for i in range(0, len(sequence), width)]
    return "\n".join([header, *lines]) + "\n"


class QueryService:
    def __init__(
        self,
        read: ReadModel,
        uow_factory: UnitOfWorkFactory,
        registry: QcRegistry,
        store: ObjectStore,
    ) -> None:
        self.read = read
        self.uow_factory = uow_factory
        self.registry = registry
        self.store = store

    def _roles(self, actor: Actor, project_id: str) -> frozenset[Role]:
        with self.uow_factory() as uow:
            return uow.members.roles(actor.user_id, project_id)

    def _visible(self, actor: Actor, project_id: str, tenant_id: str, action: Action) -> None:
        if tenant_id != actor.tenant_id:
            raise NotFound("Not found.")
        authorize(self._roles(actor, project_id), action)

    def me(self, actor: Actor, display_name: str) -> Json:
        return {
            "user_id": actor.user_id,
            "display_name": display_name,
            "projects": self.read.projects_for_user(actor.user_id),
        }

    def task(self, actor: Actor, task_id: str) -> Json:
        task = self.read.task(task_id)
        if task is None:
            raise NotFound("Task not found.")
        self._visible(actor, task["project_id"], task["tenant_id"], Action.VIEW)
        return task

    def tasks(
        self, actor: Actor, project_id: str, cursor: Cursor, limit: int
    ) -> tuple[list[Json], str | None]:
        authorize(self._roles(actor, project_id), Action.VIEW)
        return self.read.tasks(project_id, min(limit, MAX_PAGE), cursor)

    def candidates(
        self, actor: Actor, task_id: str, offset: int, limit: int
    ) -> tuple[list[Json], int | None]:
        task = self.task(actor, task_id)
        if task["run_id"] is None:
            return [], None
        with self.uow_factory() as uow:
            rows = uow.candidates.list_for_run(task["run_id"])
        page = rows[offset : offset + min(limit, MAX_PAGE)]
        items = [self._present(row) for row in page if row.candidate.qc is not None]
        next_offset = offset + len(page) if offset + len(page) < len(rows) else None
        return items, next_offset

    def candidate(self, actor: Actor, candidate_id: str) -> Json:
        with self.uow_factory() as uow:
            row = uow.candidates.get(candidate_id)
        if row is None or row.tenant_id != actor.tenant_id:
            raise NotFound("Candidate not found.")
        authorize(self._roles(actor, row.project_id), Action.VIEW)
        return self._present(row)

    def _present(self, row: CandidateRow) -> Json:
        """Contract-valid candidate plus the review state the workspace needs."""
        candidate = row.candidate
        assert candidate.qc is not None
        return {
            "candidate": candidate_to_wire(candidate, row.extraction_record_index),
            "review": {
                "resolutions": dict(candidate.resolutions),
                "approved_revision": candidate.approved_revision,
                "typed_sequence": candidate.typed_sequence,
                "allowed_resolutions": {
                    issue.rule_id: sorted(self.registry.rules[issue.rule_id].allowed_resolutions)
                    for issue in candidate.qc.issues
                },
            },
        }

    def document(self, actor: Actor, task_id: str) -> Json:
        task = self.task(actor, task_id)
        if task["run_id"] is None:
            raise NotFound("This task has no extraction run yet.")
        with self.uow_factory() as uow:
            blocks = uow.runs.blocks(task["run_id"])
        return {
            "run": self.read.run(task["run_id"]),
            "offset_unit": "unicode_codepoint",
            "blocks": [
                {
                    "block_id": b.block_id,
                    "type": b.type,
                    "raw_text": b.raw_text,
                    "location": b.location,
                    "extraction_method": b.extraction_method,
                }
                for b in blocks
            ],
        }

    def records(
        self,
        actor: Actor,
        *,
        project_id: str | None,
        q: str | None,
        sequence: str | None,
        min_length: int | None,
        max_length: int | None,
        cursor: Cursor,
        limit: int,
    ) -> tuple[list[Json], str | None]:
        if project_id is not None:
            authorize(self._roles(actor, project_id), Action.VIEW)
            project_ids = [project_id]
        else:
            project_ids = [
                p["project_id"]
                for p in self.read.projects_for_user(actor.user_id)
                if {Role(r) for r in p["roles"]} & PERMISSIONS[Action.VIEW]
            ]
        sha = None
        if sequence:
            normalized = normalize(sequence).sequence
            if not normalized:
                raise InvalidRequest("The sequence to search for is empty.")
            sha = sequence_sha256(normalized)
        return self.read.records(
            project_ids,
            q=q,
            sequence_sha256=sha,
            min_length=min_length,
            max_length=max_length,
            limit=min(limit, MAX_PAGE),
            cursor=cursor,
        )

    def record(self, actor: Actor, record_id: str) -> Json:
        record = self.read.record(record_id)
        if record is None:
            raise NotFound("Record not found.")
        self._visible(actor, record["project_id"], record["tenant_id"], Action.VIEW)
        return record

    def export_fasta(self, actor: Actor, record_id: str, version_no: int) -> tuple[str, str]:
        record = self.read.record(record_id)
        if record is None:
            raise NotFound("Record not found.")
        self._visible(actor, record["project_id"], record["tenant_id"], Action.EXPORT)
        version = next((v for v in record["versions"] if v["version_no"] == version_no), None)
        if version is None:
            raise NotFound("Version not found.")
        header = fasta_header(record["name"], record_id, version_no)
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", record["name"])[:80] or "record"
        return to_fasta(header, version["sequence"]), f"{filename}_v{version_no}.fasta"

    def original(self, actor: Actor, file_id: str) -> tuple[bytes, str]:
        """Original bytes after re-authorizing; served as an attachment, never inline."""
        with self.uow_factory() as uow:
            row = uow.files.get(file_id)
        if row is None:
            raise NotFound("File not found.")
        self._visible(actor, row.project_id, row.tenant_id, Action.VIEW)
        if row.security_status != "clean":
            raise NotFound("File not available.")
        return self.store.get(row.object_key), row.original_name
