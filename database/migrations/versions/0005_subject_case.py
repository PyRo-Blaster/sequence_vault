"""Sign-in names are unique regardless of case (they are compared case-insensitively).

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users differing only in case cannot be merged automatically: each has its own grants
    # and audit trail. Stop with the list so an operator decides (database/migrations/README.md).
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT lower(subject) AS subject, count(*) AS users FROM app_user "
                "GROUP BY lower(subject) HAVING count(*) > 1 ORDER BY 1"
            )
        )
        .all()
    )
    if duplicates:
        listed = ", ".join(f"{row.subject} ({row.users} users)" for row in duplicates)
        raise RuntimeError(
            "Sign-in names that differ only in case must be merged before migration 0005: " + listed
        )
    op.execute("CREATE UNIQUE INDEX app_user_subject_lower ON app_user (lower(subject))")


def downgrade() -> None:
    op.execute("DROP INDEX app_user_subject_lower")
