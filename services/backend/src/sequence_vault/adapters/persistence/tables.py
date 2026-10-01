"""SQLAlchemy Core tables mirroring database/migrations. A test compares the two."""

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()


def _created() -> Column[Any]:
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


tenant = Table(
    "tenant",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
)

project = Table(
    "project",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("name", Text, nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "name"),
)

app_user = Table(
    "app_user",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("subject", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False),
)

project_member = Table(
    "project_member",
    metadata,
    Column("project_id", Text, ForeignKey("project.id"), primary_key=True),
    Column("user_id", Text, ForeignKey("app_user.id"), primary_key=True),
    Column("role", Text, primary_key=True),
)

source_file = Table(
    "source_file",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("project_id", Text, ForeignKey("project.id"), nullable=False),
    Column("uploaded_by", Text, ForeignKey("app_user.id"), nullable=False),
    Column("original_name", Text, nullable=False),
    Column("declared_bytes", BigInteger, nullable=False),
    Column("declared_sha256", Text, nullable=False),
    Column("byte_count", BigInteger),
    Column("sha256", Text),
    Column("object_key", Text, nullable=False, unique=True),
    Column("detected_type", Text),
    Column("security_status", Text, nullable=False, server_default="awaiting_upload"),
    _created(),
)

file_task = Table(
    "file_task",
    metadata,
    Column("id", Text, primary_key=True),
    Column("file_id", Text, ForeignKey("source_file.id"), nullable=False, unique=True),
    Column("status", Text, nullable=False),
    Column("failure_code", Text),
    Column("current_run_id", Text, ForeignKey("extraction_run.id", use_alter=True)),
    Column("generation", Integer, nullable=False, server_default="1"),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

extraction_run = Table(
    "extraction_run",
    metadata,
    Column("id", Text, primary_key=True),
    Column("file_id", Text, ForeignKey("source_file.id"), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("parser_version", Text),
    Column("model_version", Text),
    Column("prompt_version", Text),
    Column("schema_version", Text, nullable=False),
    Column("qc_version", Text, nullable=False),
    Column("parse_options", JSONB),
    Column("source_encoding", Text),
    Column("coverage", JSONB),
    Column("extraction_result", JSONB),
    _created(),
    UniqueConstraint("file_id", "generation"),
)

document_block = Table(
    "document_block",
    metadata,
    Column("run_id", Text, ForeignKey("extraction_run.id"), primary_key=True),
    Column("block_id", Text, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("type", Text, nullable=False),
    Column("raw_text", Text, nullable=False),
    Column("location", JSONB, nullable=False),
    Column("extraction_method", Text, nullable=False),
    UniqueConstraint("run_id", "position"),
)

candidate = Table(
    "candidate",
    metadata,
    Column("id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey("extraction_run.id"), nullable=False),
    Column("file_id", Text, ForeignKey("source_file.id"), nullable=False),
    Column("project_id", Text, ForeignKey("project.id"), nullable=False),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("extraction_record_index", Integer),
    Column("revision", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("body", JSONB, nullable=False),
    _created(),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("candidate_run", "run_id"),
)

review = Table(
    "review",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("candidate_id", Text, ForeignKey("candidate.id"), nullable=False),
    Column("run_id", Text, ForeignKey("extraction_run.id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("decision", Text, nullable=False),
    Column("reviewer_id", Text, ForeignKey("app_user.id"), nullable=False),
    _created(),
)

sequence_entity = Table(
    "sequence_entity",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("molecule_type", Text, nullable=False),
    Column("canonical_sequence", Text, nullable=False),
    Column("length", Integer, nullable=False),
    Column("sha256", Text, nullable=False),
    _created(),
    UniqueConstraint("tenant_id", "molecule_type", "sha256"),
)

record = Table(
    "record",
    metadata,
    Column("id", Text, primary_key=True),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("project_id", Text, ForeignKey("project.id"), nullable=False),
    Column("name_key", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    _created(),
    UniqueConstraint("project_id", "name_key"),
)

record_version = Table(
    "record_version",
    metadata,
    Column("id", Text, primary_key=True),
    Column("record_id", Text, ForeignKey("record.id"), nullable=False),
    Column("version_no", Integer, nullable=False),
    Column("sequence_entity_id", Text, ForeignKey("sequence_entity.id"), nullable=False),
    Column("previous_version_id", Text, ForeignKey("record_version.id")),
    Column("is_current", Boolean, nullable=False),
    Column("created_by", Text, ForeignKey("app_user.id"), nullable=False),
    _created(),
    UniqueConstraint("record_id", "version_no"),
)

provenance = Table(
    "provenance",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("record_version_id", Text, ForeignKey("record_version.id"), nullable=False),
    Column("candidate_id", Text, ForeignKey("candidate.id"), nullable=False),
    Column("candidate_revision", Integer, nullable=False),
    Column("run_id", Text, ForeignKey("extraction_run.id"), nullable=False),
    Column("file_id", Text, ForeignKey("source_file.id"), nullable=False),
    Column("approved_by", Text, ForeignKey("app_user.id"), nullable=False),
    Column("committed_by", Text, ForeignKey("app_user.id"), nullable=False),
    Column("evidence", JSONB, nullable=False),
    Column("transformation_log", JSONB, nullable=False),
    _created(),
)

commit_result = Table(
    "commit_result",
    metadata,
    Column("idempotency_key", Text, primary_key=True),
    Column("candidate_id", Text, ForeignKey("candidate.id"), primary_key=True),
    Column("approved_revision", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("record_id", Text, ForeignKey("record.id")),
    Column("record_version_id", Text, ForeignKey("record_version.id")),
    _created(),
)

audit_event = Table(
    "audit_event",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("tenant_id", Text, ForeignKey("tenant.id"), nullable=False),
    Column("actor_id", Text),
    Column("event", Text, nullable=False),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    Column("detail", JSONB, nullable=False, server_default="{}"),
    _created(),
    Index("audit_event_entity", "entity_type", "entity_id"),
)

stage_job = Table(
    "stage_job",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("task_id", Text, ForeignKey("file_task.id"), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("stage", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("available_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("lease_owner", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("last_error", Text),
    _created(),
    UniqueConstraint("task_id", "generation", "stage"),
)
