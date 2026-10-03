"""P7 recovery drill: back up, restore into a fresh database and store, compare (design 9)."""

import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from sequence_vault.adapters.persistence.repositories import SqlUnitOfWorkFactory
from sequence_vault.settings import REPO_ROOT, Settings
from tests.integration.test_legacy_migration import ROWS, Migration, export
from tests.integration.test_pipeline import Env


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "backup", REPO_ROOT / "infrastructure/backup/backup.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup_tool = load()


def settings(database_url: str, objects: Path) -> Settings:
    return Settings.from_env(
        {
            "SEQUENCE_VAULT_ENV": "development",
            "SEQUENCE_VAULT_DATABASE_URL": database_url,
            "SEQUENCE_VAULT_STORAGE": "local",
            "SEQUENCE_VAULT_LOCAL_STORAGE_DIR": str(objects),
            "SEQUENCE_VAULT_SCANNER": "development",
        }
    )


@pytest.fixture
def empty_database(admin_url: str) -> Iterator[str]:
    name = f"sv_restore_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {name}"))
    try:
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


@pytest.fixture
def populated(engine: Engine, database_url: str, tmp_path: Path) -> tuple[Migration, Settings]:
    env = Env(engine, tmp_path)
    migration = Migration(env)
    migration.run(export(ROWS))
    return migration, settings(database_url, tmp_path / "objects")


def test_a_restore_reproduces_records_hashes_objects_and_permissions(
    populated: tuple[Migration, Settings], empty_database: str, tmp_path: Path
) -> None:
    migration, source = populated
    made = backup_tool.backup(source, tmp_path / "backups")
    assert backup_tool.verify(made) == []

    target = settings(empty_database, tmp_path / "restored-objects")
    assert backup_tool.restore(target, made) == []

    engine = create_engine(empty_database)
    try:
        with engine.connect() as connection:
            restored = backup_tool.fingerprint(connection, backup_tool.build_store(target))
        uow = SqlUnitOfWorkFactory(engine)
        with uow() as restored_uow:
            roles = restored_uow.members.roles(migration.operator.user_id, migration.env.project)
    finally:
        engine.dispose()
    assert restored["counts"]["record_version"] == 2
    assert restored["counts"]["legacy_record"] == 6
    assert restored["object_errors"] == [] and restored["entity_hash_errors"] == []
    assert {role.value for role in roles} == {"uploader", "reviewer"}


def test_a_damaged_backup_is_refused(
    populated: tuple[Migration, Settings], empty_database: str, tmp_path: Path
) -> None:
    _, source = populated
    made = backup_tool.backup(source, tmp_path / "backups")
    [stored] = [p for p in (made / "objects").rglob("*") if p.is_file()]
    stored.write_bytes(stored.read_bytes() + b"\n")

    assert backup_tool.verify(made) == [str(stored.relative_to(made))]
    target = settings(empty_database, tmp_path / "restored-objects")
    assert backup_tool.restore(target, made) == [f"checksum: {stored.relative_to(made)}"]


def test_a_restore_never_overwrites_a_database(
    populated: tuple[Migration, Settings], tmp_path: Path
) -> None:
    _, source = populated
    made = backup_tool.backup(source, tmp_path / "backups")
    assert backup_tool.restore(source, made) == ["target database is not empty"]


def test_a_missing_object_is_reported(
    populated: tuple[Migration, Settings], tmp_path: Path
) -> None:
    _, source = populated
    for path in (tmp_path / "objects").rglob("*"):
        if path.is_file():
            path.unlink()
    engine = create_engine(source.database_url)
    try:
        with engine.connect() as connection:
            print_ = backup_tool.fingerprint(connection, backup_tool.build_store(source))
    finally:
        engine.dispose()
    assert len(print_["object_errors"]) == 1
