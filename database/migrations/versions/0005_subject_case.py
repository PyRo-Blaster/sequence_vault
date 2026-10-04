"""Sign-in names are unique regardless of case (they are compared case-insensitively).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX app_user_subject_lower ON app_user (lower(subject))")


def downgrade() -> None:
    op.execute("DROP INDEX app_user_subject_lower")
