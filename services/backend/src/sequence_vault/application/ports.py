"""Interfaces the use cases need; adapters implement them."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self

from sequence_vault.application.authorization import Role
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.publication import StoredEntity, StoredRecord
from sequence_vault.domain.task import FileTask

Json = dict[str, Any]


class ConcurrentUpdate(Exception):
    """A uniqueness or serialization conflict with another transaction; retry once."""


@dataclass(frozen=True, slots=True)
class CandidateRow:
    candidate: Candidate
    tenant_id: str
    project_id: str
    file_id: str
    extraction_record_index: int | None


@dataclass(frozen=True, slots=True)
class FileRow:
    file_id: str
    tenant_id: str
    project_id: str
    uploaded_by: str
    original_name: str
    declared_bytes: int
    declared_sha256: str
    byte_count: int | None
    sha256: str | None
    object_key: str
    detected_type: str | None
    security_status: str


DEFAULT_PARSE_OPTIONS: Json = {"tracked_changes_view": "not_applicable"}


@dataclass(frozen=True, slots=True)
class TaskRow:
    task: FileTask
    file_id: str
    current_run_id: str | None
    generation: int
    parse_options: Json = field(default_factory=lambda: dict(DEFAULT_PARSE_OPTIONS))


@dataclass(frozen=True, slots=True)
class RunRow:
    run_id: str
    file_id: str
    generation: int
    qc_version: str
    schema_version: str
    parser_version: str | None
    model_version: str | None
    prompt_version: str | None
    coverage: Json | None
    extraction_result: Json | None


@dataclass(frozen=True, slots=True)
class BlockRow:
    block_id: str
    type: str
    raw_text: str
    location: Json
    extraction_method: str


@dataclass(frozen=True, slots=True)
class CurrentVersion:
    version_id: str
    version_no: int
    sequence: str


@dataclass(frozen=True, slots=True)
class StoredCommit:
    approved_revision: int
    status: str
    record_id: str | None
    record_version_id: str | None


class Members(Protocol):
    def roles(self, user_id: str, project_id: str) -> frozenset[Role]: ...


class Candidates(Protocol):
    def get(self, candidate_id: str, *, for_update: bool = False) -> CandidateRow | None: ...
    def add(self, row: CandidateRow) -> None: ...
    def save(self, candidate: Candidate) -> None: ...
    def list_for_run(self, run_id: str) -> list[CandidateRow]: ...


class Files(Protocol):
    def get(self, file_id: str) -> FileRow | None: ...
    def create(self, row: FileRow) -> None: ...
    def mark_uploaded(self, file_id: str, byte_count: int, sha256: str) -> None: ...
    def set_security(self, file_id: str, status: str, detected_type: str | None) -> None: ...


class Tasks(Protocol):
    def get(self, task_id: str, *, for_update: bool = False) -> TaskRow | None: ...
    def get_by_file(self, file_id: str, *, for_update: bool = False) -> TaskRow | None: ...
    def create(self, row: TaskRow) -> None: ...
    def save(self, row: TaskRow) -> None: ...


class Runs(Protocol):
    def get(self, run_id: str) -> RunRow | None: ...
    def blocks(self, run_id: str) -> list[BlockRow]: ...
    def create(self, row: RunRow, *, parse_options: Json, source_encoding: str) -> None: ...
    def add_blocks(self, run_id: str, blocks: list[Json]) -> None: ...
    def set_extraction(
        self, run_id: str, result: Json, *, model_version: str | None, prompt_version: str | None
    ) -> None: ...


class Jobs(Protocol):
    def enqueue(self, task_id: str, generation: int, stage: str) -> None: ...


class Publication(Protocol):
    def find_entities(
        self, tenant_id: str, molecule_type: str, sha256: str
    ) -> list[StoredEntity]: ...
    def find_entities_in_project(
        self, project_id: str, molecule_type: str, sha256: str
    ) -> list[StoredEntity]: ...
    def create_entity(self, tenant_id: str, molecule_type: str, sequence: str) -> str: ...
    def find_record(
        self, project_id: str, name_key: str, *, for_update: bool = False
    ) -> StoredRecord | None: ...
    def create_record(
        self, tenant_id: str, project_id: str, name_key: str, display: str
    ) -> str: ...
    def current_version(self, record_id: str) -> CurrentVersion | None: ...
    def supersede(self, version_id: str) -> None: ...
    def add_version(
        self,
        record_id: str,
        version_no: int,
        entity_id: str,
        previous_version_id: str | None,
        created_by: str,
    ) -> str: ...
    def add_provenance(
        self, record_version_id: str, row: CandidateRow, committed_by: str
    ) -> None: ...


class Reviews(Protocol):
    def add(
        self, candidate_id: str, run_id: str, revision: int, decision: str, reviewer: str
    ) -> None: ...


class Audit(Protocol):
    def record(
        self,
        tenant_id: str,
        actor_id: str | None,
        event: str,
        entity_type: str,
        entity_id: str,
        detail: Json | None = None,
    ) -> None: ...


class Commits(Protocol):
    def get(self, key: str, candidate_id: str) -> StoredCommit | None: ...
    def put(self, key: str, candidate_id: str, result: StoredCommit) -> None: ...


@dataclass(frozen=True, slots=True)
class LegacyBatchRow:
    batch_id: str
    tenant_id: str
    project_id: str
    file_id: str
    operator_id: str
    source_system: str
    legacy_project: str
    exported_at: datetime | None


@dataclass(frozen=True, slots=True)
class LegacyLink:
    """The latest import of one legacy ID and where it stands now."""

    legacy_id: str
    legacy_name: str
    sequence_sha256: str
    candidate_id: str
    candidate_status: str
    published_sequence: str | None


class LegacyRecords(Protocol):
    def create_batch(self, row: LegacyBatchRow) -> None: ...
    def add(
        self,
        batch_id: str,
        project_id: str,
        legacy_id: str,
        legacy_name: str,
        created_at: datetime | None,
        updated_at: datetime | None,
        sequence_sha256: str,
        candidate_id: str,
    ) -> None: ...
    def latest(self, project_id: str, legacy_ids: Sequence[str]) -> dict[str, LegacyLink]: ...
    def finish_batch(self, batch_id: str, report: Json) -> None: ...
    def grants(self, project_id: str) -> frozenset[tuple[str, str]]:
        """(sign-in subject, role) pairs currently granted in the project."""
        ...


class UnitOfWork(Protocol):
    """One database transaction. Leaving the block without commit() rolls back."""

    @property
    def members(self) -> Members: ...
    @property
    def candidates(self) -> Candidates: ...
    @property
    def files(self) -> Files: ...
    @property
    def tasks(self) -> Tasks: ...
    @property
    def runs(self) -> Runs: ...
    @property
    def publication(self) -> Publication: ...
    @property
    def reviews(self) -> Reviews: ...
    @property
    def audit(self) -> Audit: ...
    @property
    def commits(self) -> Commits: ...
    @property
    def jobs(self) -> Jobs: ...
    @property
    def legacy(self) -> LegacyRecords: ...

    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


SequenceOfRows = Sequence[CandidateRow]


class TransientError(Exception):
    """A temporary infrastructure failure; the stage is retried with backoff."""


class ScannerUnavailable(TransientError):
    pass


class ParseFailed(Exception):
    """Deterministic parse failure; never retried."""

    def __init__(self, message: str, *, code: str = "parse_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    clean: bool
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class Detection:
    """``format`` is None when the content is not acceptable; ``reason`` explains why."""

    format: str | None
    reason: str


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...


class Scanner(Protocol):
    def scan(self, data: bytes) -> ScanVerdict: ...


class TypeDetector(Protocol):
    def detect(self, data: bytes, file_name: str) -> Detection: ...


class DocumentParser(Protocol):
    def parse(
        self, format: str, data: bytes, *, file_id: str, run_id: str, parse_options: Json
    ) -> Json: ...


@dataclass(frozen=True, slots=True)
class Job:
    """One pipeline stage to run for one task generation."""

    job_id: int
    task_id: str
    generation: int
    stage: str
    attempts: int
