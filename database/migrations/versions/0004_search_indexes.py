"""Indexes for record search across projects (docs/operations/capacity.md).

Search orders by (name_key, id) over several projects; the (project_id, name_key) index cannot
serve that order, so every match was joined and sorted before the page limit. Exact-sequence
search filters on sha256 alone, which is the third column of the entity unique index.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX record_name_order ON record (name_key, id)")
    op.execute("CREATE INDEX sequence_entity_sha256 ON sequence_entity (sha256)")


def downgrade() -> None:
    op.execute("DROP INDEX sequence_entity_sha256")
    op.execute("DROP INDEX record_name_order")
