"""Store the parse options a user chose for the next run (tracked-changes view, design 5).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE file_task ADD COLUMN parse_options jsonb NOT NULL "
        'DEFAULT \'{"tracked_changes_view": "not_applicable"}\''
    )


def downgrade() -> None:
    op.execute("ALTER TABLE file_task DROP COLUMN parse_options")
