"""Legacy migration batches and the legacy IDs they imported (design, "Legacy System Migration").

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE legacy_batch (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenant(id),
    project_id text NOT NULL REFERENCES project(id),
    file_id text NOT NULL REFERENCES source_file(id),
    operator_id text NOT NULL REFERENCES app_user(id),
    source_system text NOT NULL,
    legacy_project text NOT NULL,
    exported_at timestamptz,
    report jsonb,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE legacy_record (
    id bigserial PRIMARY KEY,
    batch_id text NOT NULL REFERENCES legacy_batch(id),
    project_id text NOT NULL REFERENCES project(id),
    legacy_id text NOT NULL,
    legacy_name text NOT NULL,
    legacy_created_at timestamptz,
    legacy_updated_at timestamptz,
    sequence_sha256 text NOT NULL,
    candidate_id text NOT NULL REFERENCES candidate(id) UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (batch_id, legacy_id)
);

CREATE INDEX legacy_record_lookup ON legacy_record (project_id, legacy_id);

CREATE TRIGGER legacy_record_immutable BEFORE UPDATE OR DELETE ON legacy_record
    FOR EACH ROW EXECUTE FUNCTION forbid_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP TABLE legacy_record, legacy_batch")
