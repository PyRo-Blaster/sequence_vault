"""Run the reviewed Alembic migrations in database/migrations."""

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine, text

log = logging.getLogger(__name__)

# Held for the whole upgrade, so API replicas that migrate at start-up take turns.
_LOCK = 0x5E9_7A17


def migrations_dir() -> Path:
    configured = os.environ.get("SEQUENCE_VAULT_MIGRATIONS_DIR")
    if configured:
        return Path(configured)
    # services/backend/src/sequence_vault/adapters/persistence -> repository root
    return Path(__file__).resolve().parents[6] / "database"


class DatabaseAhead(RuntimeError):
    """The database carries a revision this code does not know: a newer release migrated it.
    Migrations are additive, so this release can still run against it (a rollback)."""


def _revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def upgrade(database_url: str, revision: str = "head") -> tuple[str | None, str | None]:
    """Apply migrations under a PostgreSQL advisory lock; a second caller waits, then finds
    nothing left to do. Returns the revisions before and after. Raises DatabaseAhead,
    changing nothing, when the database is newer than these migrations."""
    config = Config(str(migrations_dir() / "alembic.ini"))
    # ConfigParser interpolates "%"; a percent-encoded password must reach Alembic intact.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    known = {script.revision for script in ScriptDirectory.from_config(config).walk_revisions()}
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            locked = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK}
            ).scalar()
            if not locked:
                log.info("waiting for another process to finish database migrations")
                connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _LOCK})
            connection.commit()
            try:
                before = _revision(connection)
                connection.commit()
                if before is not None and before not in known:
                    raise DatabaseAhead(
                        f"The database is at revision {before}, newer than this release."
                    )
                config.attributes["connection"] = connection  # env.py migrates on it
                command.upgrade(config, revision)
                after = _revision(connection)
                connection.commit()
                return before, after
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK})
                connection.commit()
    finally:
        engine.dispose()
