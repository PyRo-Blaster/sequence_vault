"""Alembic environment: runs reviewed migrations against SEQUENCE_VAULT_DATABASE_URL.

`sequence_vault.adapters.persistence.migrate.upgrade` passes its own connection (it holds the
migration lock); the alembic command line connects here.
"""

import os

from alembic import context
from sqlalchemy import Connection, create_engine


def run(connection: Connection) -> None:
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


given = context.config.attributes.get("connection")
if given is not None:
    run(given)
else:
    url = (
        context.config.get_main_option("sqlalchemy.url")
        or os.environ["SEQUENCE_VAULT_DATABASE_URL"]
    )
    engine = create_engine(url)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
