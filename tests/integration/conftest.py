"""PostgreSQL for integration tests.

Uses SEQUENCE_VAULT_TEST_DATABASE_URL (an admin URL, as in CI) when set. Otherwise starts a
throwaway local cluster with initdb. The schema is migrated once into a template database
and every test gets a fresh copy.
"""

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from sequence_vault.adapters.persistence.migrate import upgrade

TEMPLATE = "sequence_vault_template"


def _postgres_bin() -> Path | None:
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)
    found = shutil.which("pg_ctl")
    if found:
        candidates.insert(0, Path(found).parent)
    return next((path for path in candidates if (path / "initdb").exists()), None)


def _as_postgres(command: list[str]) -> list[str]:
    return ["runuser", "-u", "postgres", "--", *command] if os.geteuid() == 0 else command


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def admin_url() -> Iterator[str]:
    configured = os.environ.get("SEQUENCE_VAULT_TEST_DATABASE_URL")
    if configured:
        yield configured
        return
    bindir = _postgres_bin()
    if bindir is None:
        pytest.skip("No PostgreSQL: set SEQUENCE_VAULT_TEST_DATABASE_URL or install the server")
    workdir = Path(tempfile.mkdtemp(prefix="sv-pg-"))
    workdir.chmod(0o777)
    data = workdir / "data"
    port = _free_port()
    subprocess.run(
        _as_postgres([str(bindir / "initdb"), "-D", str(data), "-A", "trust", "-U", "postgres"]),
        check=True,
        capture_output=True,
    )
    options = f"-p {port} -k {workdir} -c listen_addresses=127.0.0.1 -c fsync=off"
    log = workdir / "server.log"
    # The server inherits pg_ctl's stdout, so never pipe it: write to a log file instead.
    subprocess.run(
        _as_postgres(
            [str(bindir / "pg_ctl"), "-D", str(data), "-l", str(log), "-o", options, "-w", "start"]
        ),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            _as_postgres([str(bindir / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"]),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(workdir, ignore_errors=True)


def _admin(url: str) -> Engine:
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def template_url(admin_url: str) -> str:
    admin = _admin(admin_url)
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {TEMPLATE}"))
        connection.execute(text(f"CREATE DATABASE {TEMPLATE}"))
    admin.dispose()
    url = make_url(admin_url).set(database=TEMPLATE).render_as_string(hide_password=False)
    upgrade(url)
    return url


@pytest.fixture
def database_url(admin_url: str, template_url: str) -> Iterator[str]:
    name = f"sv_test_{uuid.uuid4().hex[:12]}"
    admin = _admin(admin_url)
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE}"))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()
