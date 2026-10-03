"""Response models. They make the OpenAPI document precise, so the web app's generated types
match exactly what the server sends. Candidate fields mirror candidate.schema.json, and
tests also validate candidate payloads against that schema."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    # Undeclared fields (such as internal tenant IDs) are dropped from responses.
    model_config = ConfigDict(extra="ignore")


class Project(Model):
    project_id: str
    name: str
    roles: list[Literal["uploader", "reviewer", "viewer", "project_admin"]]


class Limits(Model):
    max_file_bytes: int
    max_files_per_batch: int


class Me(Model):
    user_id: str
    display_name: str
    projects: list[Project]
    limits: Limits
    accepted_extensions: list[str]


class Health(Model):
    status: str
    dev_login: bool


class UploadCreated(Model):
    file_id: str
    upload_url: str
    file_name: str


class TaskState(Model):
    task_id: str
    status: str
    generation: int | None = None


class Task(Model):
    task_id: str
    file_id: str
    project_id: str
    file_name: str
    byte_count: int | None
    detected_type: str | None
    security_status: str
    status: str
    failure_code: str | None
    generation: int
    run_id: str | None
    candidate_counts: dict[str, int]
    created_at: str
    updated_at: str


class TaskPage(Model):
    items: list[Task]
    next_cursor: str | None


class Span(Model):
    block_id: str
    start: int
    end: int


class OrderedSpan(Span):
    order: int


class Name(Model):
    value: str
    source: Literal["fasta_header", "table_cell", "heading", "filename", "manual", "legacy_import"]
    evidence: Span | None


class Transformation(Model):
    rule_id: str
    operation: str
    reason: str
    positions: list[int]


class Issue(Model):
    rule_id: str
    severity: Literal["INFO", "REVIEW", "BLOCK"]
    message: str
    evidence: list[Span]


class CandidateWire(Model):
    schema_version: Literal["1.0"]
    candidate_id: str
    run_id: str
    # Optional in the contract: omitted (never null) for legacy and split candidates.
    extraction_record_index: int | None = Field(default=None, exclude_if=lambda v: v is None)
    revision: int
    name: Name | None
    extracted_names: list[Name]
    sequence_spans: list[OrderedSpan]
    raw_text: str
    normalized_sequence: str
    molecule_type: Literal["protein", "nucleic_acid", "uncertain"]
    completeness: Literal["complete", "fragment", "unknown"]
    status: Literal[
        "DRAFT",
        "NEEDS_REVIEW",
        "BLOCKED",
        "APPROVED",
        "COMMITTED",
        "REJECTED",
        "PENDING_CONTENT",
        "ARCHIVED",
        "SUPERSEDED",
    ]
    origin: Literal["extracted", "manual_revision", "legacy_import"]
    transformation_log: list[Transformation]
    issues: list[Issue]
    qc_version: str


class ReviewState(Model):
    resolutions: dict[str, str]
    approved_revision: int | None
    typed_sequence: str | None
    allowed_resolutions: dict[str, list[str]]


class CandidateEnvelope(Model):
    candidate: CandidateWire
    review: ReviewState


class CandidatePage(Model):
    items: list[CandidateEnvelope]
    next_cursor: str | None


class Block(Model):
    block_id: str
    type: str
    raw_text: str
    location: dict[str, Any]
    extraction_method: str


class Run(Model):
    run_id: str
    generation: int
    parser_version: str | None
    model_version: str | None
    prompt_version: str | None
    schema_version: str
    qc_version: str
    parse_options: dict[str, Any] | None
    source_encoding: str | None
    coverage: dict[str, Any] | None


class Document(Model):
    run: Run | None
    offset_unit: Literal["unicode_codepoint"]
    blocks: list[Block]


class CommitResult(Model):
    candidate_id: str
    status: Literal["COMMITTED", "ALREADY_COMMITTED", "CONFLICT", "FAILED"]
    reason: str | None
    record_id: str | None
    record_version_id: str | None


class CommitResponse(Model):
    results: list[CommitResult]
    counts: dict[str, int]


class RecordSummary(Model):
    record_id: str
    name: str
    project_id: str
    project: str
    version_no: int
    length: int
    sha256: str
    updated_at: str


class RecordPage(Model):
    items: list[RecordSummary]
    next_cursor: str | None


class Provenance(Model):
    candidate_id: str
    candidate_revision: int
    run_id: str
    file_id: str
    file_name: str
    evidence: dict[str, Any]
    transformation_log: list[Transformation]
    approved_by: str
    committed_by: str
    committed_at: str


class Version(Model):
    version_id: str
    version_no: int
    is_current: bool
    previous_version_id: str | None
    sequence: str
    length: int
    sha256: str
    created_by: str
    created_at: str
    provenance: list[Provenance]


class RecordDetail(Model):
    record_id: str
    project_id: str
    name: str
    created_at: str
    versions: list[Version]


class Member(Model):
    user_id: str
    subject: str
    display_name: str
    roles: list[Literal["uploader", "reviewer", "viewer", "project_admin"]]


class MemberList(Model):
    items: list[Member]


class FormatQuality(Model):
    format: str
    tasks: int
    failed: int
    failure_rate: float | None


class RunVersions(Model):
    parser_version: str | None
    model_version: str | None
    prompt_version: str | None
    runs: int


class Quality(Model):
    tasks: dict[str, int]
    failure_codes: dict[str, int]
    formats: list[FormatQuality]
    candidates: dict[str, int]
    manual_revision_rate: float | None
    rename_rate: float | None
    commits: dict[str, int]
    records: int
    runs: list[RunVersions]


class ErrorBody(Model):
    code: str
    message: str
    request_id: str
    details: Any = None
    retryable: bool
