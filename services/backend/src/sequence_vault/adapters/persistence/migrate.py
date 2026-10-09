"""Run the reviewed Alembic migrations in database/migrations."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

# Held for the whole upgrade, so API replicas that migrate at start-up take turns.
_LOCK = 0x5E9_7A17


def migrations_dir() -> Path:
    configured = os.environ.get("SEQUENCE_VAULT_MIGRATIONS_DIR")
    if configured:
        return Path(configured)
    # services/backend/src/sequence_vault/adapters/persistence -> repository root
    return Path(__file__).resolve().parents[6] / "database"


def upgrade(database_url: str, revision: str = "head") -> None:
    """Apply migrations under a PostgreSQL advisory lock; a second caller waits, then finds
    nothing left to do."""
    config = Config(str(migrations_dir() / "alembic.ini"))
    # ConfigParser interpolates "%"; a percent-encoded password must reach Alembic intact.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _LOCK})
            connection.commit()
            try:
                config.attributes["connection"] = connection  # env.py migrates on it
                command.upgrade(config, revision)
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK})
                connection.commit()
    finally:
        engine.dispose()
