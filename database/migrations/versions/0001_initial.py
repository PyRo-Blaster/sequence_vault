"""Initial schema: projects, files, runs, evidence, candidates, published records, audit, jobs.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLES = "'uploader', 'reviewer', 'viewer', 'project_admin'"
TASK_STATUSES = (
    "'UPLOADED', 'SCANNING', 'PARSING', 'EXTRACTING', 'VALIDATING', 'REVIEW_READY', "
    "'COMPLETED', 'FAILED', 'CANCELLED', 'UNSUPPORTED'"
)
CANDIDATE_STATUSES = (
    "'DRAFT', 'NEEDS_REVIEW', 'BLOCKED', 'APPROVED', 'COMMITTED', 'REJECTED', "
    "'PENDING_CONTENT', 'ARCHIVED', 'SUPERSEDED'"
)

UPGRADE = f"""
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE tenant (
    id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE project (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant (id),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE app_user (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant (id),
    subject text NOT NULL UNIQUE,
    display_name text NOT NULL
);

CREATE TABLE project_member (
    project_id text NOT NULL REFERENCES project (id),
    user_id text NOT NULL REFERENCES app_user (id),
    role text NOT NULL CHECK (role IN ({ROLES})),
    PRIMARY KEY (project_id, user_id, role)
);

CREATE TABLE source_file (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant (id),
    project_id text NOT NULL REFERENCES project (id),
    uploaded_by text NOT NULL REFERENCES app_user (id),
    original_name text NOT NULL,
    declared_bytes bigint NOT NULL CHECK (declared_bytes >= 0),
    declared_sha256 text NOT NULL CHECK (declared_sha256 ~ '^[a-f0-9]{{64}}$'),
    byte_count bigint,
    sha256 text,
    object_key text NOT NULL UNIQUE,
    detected_type text,
    security_status text NOT NULL DEFAULT 'awaiting_upload' CHECK (
        security_status IN ('awaiting_upload', 'uploaded', 'clean', 'infected', 'scan_failed')
    ),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE file_task (
    id text PRIMARY KEY,
    file_id text NOT NULL UNIQUE REFERENCES source_file (id),
    status text NOT NULL CHECK (status IN ({TASK_STATUSES})),
    failure_code text,
    current_run_id text,
    generation integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE extraction_run (
    id text PRIMARY KEY,
    file_id text NOT NULL REFERENCES source_file (id),
    generation integer NOT NULL,
    parser_version text,
    model_version text,
    prompt_version text,
    schema_version text NOT NULL,
    qc_version text NOT NULL,
    parse_options jsonb,
    source_encoding text,
    coverage jsonb,
    extraction_result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (file_id, generation)
);

ALTER TABLE file_task
    ADD CONSTRAINT file_task_current_run_fk FOREIGN KEY (current_run_id) REFERENCES extraction_run (id);

CREATE TABLE document_block (
    run_id text NOT NULL REFERENCES extraction_run (id),
    block_id text NOT NULL,
    position integer NOT NULL,
    type text NOT NULL,
    raw_text text NOT NULL,
    location jsonb NOT NULL,
    extraction_method text NOT NULL,
    PRIMARY KEY (run_id, block_id),
    UNIQUE (run_id, position)
);

CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER document_block_immutable BEFORE UPDATE OR DELETE ON document_block
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TABLE candidate (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES extraction_run (id),
    file_id text NOT NULL REFERENCES source_file (id),
    project_id text NOT NULL REFERENCES project (id),
    tenant_id text NOT NULL REFERENCES tenant (id),
    extraction_record_index integer,
    revision integer NOT NULL CHECK (revision >= 1),
    status text NOT NULL CHECK (status IN ({CANDIDATE_STATUSES})),
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX candidate_run ON candidate (run_id);

CREATE TABLE review (
    id bigserial PRIMARY KEY,
    candidate_id text NOT NULL REFERENCES candidate (id),
    run_id text NOT NULL REFERENCES extraction_run (id),
    revision integer NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer_id text NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sequence_entity (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant (id),
    molecule_type text NOT NULL,
    canonical_sequence text NOT NULL,
    length integer NOT NULL,
    sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, molecule_type, sha256),
    CHECK (length = char_length(canonical_sequence) AND length > 0)
);

CREATE TRIGGER sequence_entity_immutable BEFORE UPDATE OR DELETE ON sequence_entity
    FOR EACH ROW EXECUTE FUNCTION forbid_change();

CREATE TABLE record (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant (id),
    project_id text NOT NULL REFERENCES project (id),
    name_key text NOT NULL,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name_key)
);

CREATE INDEX record_name_trgm ON record USING gin (name_key gin_trgm_ops);

CREATE TABLE record_version (
    id text PRIMARY KEY,
    record_id text NOT NULL REFERENCES record (id),
    version_no integer NOT NULL CHECK (version_no >= 1),
    sequence_entity_id text NOT NULL REFERENCES sequence_entity (id),
    previous_version_id text REFERENCES record_version (id),
    is_current boolean NOT NULL,
    created_by text NOT NULL REFERENCES app_user (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (record_id, version_no)
);

CREATE UNIQUE INDEX record_one_current_version ON record_version (record_id) WHERE is_current;

CREATE FUNCTION record_version_only_supersede() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'record_version rows are immutable' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.id, NEW.record_id, NEW.version_no, NEW.sequence_entity_id, NEW.previous_version_id,
        NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.record_id, OLD.version_no, OLD.sequence_entity_id, OLD.previous_version_id,
        OLD.created_by, OLD.created_at)
       OR (NEW.is_current AND NOT OLD.is_current) THEN
        RAISE EXCEPTION 'published versions can only be superseded' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER record_version_immutable BEFORE UPDATE OR DELETE ON record_version
    FOR EACH ROW EXECUTE FUNCTION record_version_only_supersede();

CREATE TABLE provenance (
    id bigserial PRIMARY KEY,
    record_version_id text NOT NULL REFERENCES record_version (id),
    candidate_id text NOT NULL REFERENCES candidate (id),
    candidate_revision integer NOT NULL,
    run_id text NOT NULL REFERENCES extraction_run (id),
    file_id text NOT NULL REFERENCES source_file (id),
    approved_by text NOT NULL REFERENCES app_user (id),
    committed_by text NOT NULL REFERENCES app_user (id),
    evidence jsonb NOT NULL,
    transformation_log jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE commit_result (
    idempotency_key text NOT NULL,
    candidate_id text NOT NULL REFERENCES candidate (id),
    approved_revision integer NOT NULL,
    status text NOT NULL,
    record_id text REFERENCES record (id),
    record_version_id text REFERENCES record_version (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (idempotency_key, candidate_id)
);

CREATE TABLE audit_event (
    id bigserial PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant (id),
    actor_id text,
    event text NOT NULL,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{{}}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_event_entity ON audit_event (entity_type, entity_id);

CREATE TABLE stage_job (
    id bigserial PRIMARY KEY,
    task_id text NOT NULL REFERENCES file_task (id),
    generation integer NOT NULL,
    stage text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    finished_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (task_id, generation, stage)
);

CREATE INDEX stage_job_ready ON stage_job (available_at) WHERE finished_at IS NULL;
"""

DOWNGRADE = """
DROP TABLE stage_job, audit_event, commit_result, provenance, record_version, record,
    sequence_entity, review, candidate, document_block CASCADE;
ALTER TABLE file_task DROP CONSTRAINT file_task_current_run_fk;
DROP TABLE extraction_run, file_task, source_file, project_member, app_user, project, tenant CASCADE;
DROP FUNCTION record_version_only_supersede();
DROP FUNCTION forbid_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
