"""Run the reviewed Alembic migrations in database/migrations."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def migrations_dir() -> Path:
    configured = os.environ.get("SEQUENCE_VAULT_MIGRATIONS_DIR")
    if configured:
        return Path(configured)
    # services/backend/src/sequence_vault/adapters/persistence -> repository root
    return Path(__file__).resolve().parents[6] / "database"


def upgrade(database_url: str, revision: str = "head") -> None:
    config = Config(str(migrations_dir() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)
