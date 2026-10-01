"""Back up and restore PostgreSQL and object storage, and prove the restore is faithful.

    uv run python infrastructure/backup/backup.py backup DEST_DIR
    uv run python infrastructure/backup/backup.py verify BACKUP_DIR
    uv run python infrastructure/backup/backup.py restore BACKUP_DIR
    uv run python infrastructure/backup/backup.py fingerprint

The SEQUENCE_VAULT_* settings select the database and object store: the source for
``backup``, the (empty) target for ``restore``.

``backup`` exports a snapshot, dumps it with pg_dump, and computes a fingerprint inside the
same snapshot: row counts, hashes over entities, record versions and permissions, and a
recomputed hash for every stored source file. The dump and the fingerprint therefore
describe exactly the same state. Objects are write-once (keys are generated, never reused),
so copying them after the snapshot captures every object it references.

``restore`` checks SHA256SUMS, restores into an empty database with pg_restore, copies the
objects into the configured store, fingerprints the result and fails unless it equals the
backup's. Fingerprints hold IDs, counts and hashes, never sequences.

Exit status: 0 success, 1 verification failed, 2 usage error.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, create_engine, func, select, text
from sqlalchemy.engine import make_url

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.application.ports import ObjectStore
from sequence_vault.entrypoints.bootstrap import build_store
from sequence_vault.settings import Settings

Json = dict[str, Any]


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def _libpq(url: str) -> tuple[str, dict[str, str]]:
    """A libpq URL without the password, and an environment that carries it."""
    parsed = make_url(url)
    env = {**os.environ}
    if parsed.password:
        env["PGPASSWORD"] = str(parsed.password)
    plain = parsed.set(drivername="postgresql", password=None)
    return plain.render_as_string(hide_password=False), env


def fingerprint(connection: Connection, store: ObjectStore) -> Json:
    """Everything a restore must reproduce, as counts and hashes."""
    counts = {
        table.name: int(connection.execute(select(func.count()).select_from(table)).scalar_one())
        for table in t.metadata.sorted_tables
    }
    revision: str = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    entities: list[str] = []
    entity_errors: list[str] = []
    for row in connection.execute(select(t.sequence_entity)):
        recomputed = hashlib.sha256(row.canonical_sequence.encode()).hexdigest()
        if recomputed != row.sha256 or len(row.canonical_sequence) != row.length:
            entity_errors.append(row.id)
        entities.append(f"{row.id}:{row.tenant_id}:{row.molecule_type}:{row.sha256}")

    versions = [
        f"{r.record_id}:{r.version_no}:{r.sequence_entity_id}:{r.is_current}"
        for r in connection.execute(select(t.record_version))
    ]
    records = [
        f"{r.id}:{r.project_id}:{r.name_key}:{r.display_name}"
        for r in connection.execute(select(t.record))
    ]
    grants = [
        f"{r.project_id}:{r.subject}:{r.role}"
        for r in connection.execute(
            select(
                t.project_member.c.project_id, t.app_user.c.subject, t.project_member.c.role
            ).join(t.app_user, t.app_user.c.id == t.project_member.c.user_id)
        )
    ]

    objects: list[str] = []
    object_errors: list[str] = []
    for row in connection.execute(
        select(t.source_file.c.id, t.source_file.c.object_key, t.source_file.c.sha256).where(
            t.source_file.c.sha256.is_not(None)
        )
    ):
        try:
            data = store.get(row.object_key)
        except Exception:  # missing object: reported, not raised
            object_errors.append(row.id)
            continue
        if hashlib.sha256(data).hexdigest() != row.sha256:
            object_errors.append(row.id)
        objects.append(f"{row.id}:{row.sha256}")

    return {
        "schema_revision": revision,
        "counts": counts,
        "entities": _digest(entities),
        "entity_hash_errors": sorted(entity_errors),
        "records": _digest(records),
        "record_versions": _digest(versions),
        "permissions": _digest(grants),
        "permission_count": len(grants),
        "objects": _digest(objects),
        "object_errors": sorted(object_errors),
    }


def _write_sums(directory: Path) -> None:
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(directory)}"
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(directory: Path) -> list[str]:
    """Files whose checksum does not match, or that are missing or unlisted."""
    sums = directory / "SHA256SUMS"
    if not sums.exists():
        return ["SHA256SUMS"]
    listed: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    present = {
        str(p.relative_to(directory))
        for p in directory.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS"
    }
    problems = sorted(present ^ set(listed))
    for name in sorted(present & set(listed)):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != listed[name]:
            problems.append(name)
    return problems


def backup(settings: Settings, destination: Path) -> Path:
    target = destination / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True)
    store = build_store(settings)
    engine = create_engine(settings.database_url)
    url, env = _libpq(settings.database_url)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            connection.begin()
            snapshot: str = connection.execute(text("SELECT pg_export_snapshot()")).scalar_one()
            subprocess.run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    f"--snapshot={snapshot}",
                    f"--file={target / 'database.dump'}",
                    url,
                ],
                check=True,
                env=env,
            )
            keys = [
                row.object_key
                for row in connection.execute(
                    select(t.source_file.c.object_key).where(t.source_file.c.sha256.is_not(None))
                )
            ]
            print_ = fingerprint(connection, store)
            server: str = connection.execute(text("SHOW server_version")).scalar_one()
    finally:
        engine.dispose()
    for key in keys:
        path = target / "objects" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(store.get(key))
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "postgres_server_version": server,
        "objects": len(keys),
        "fingerprint": print_,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _write_sums(target)
    return target


def restore(settings: Settings, source: Path) -> list[str]:
    """Restore into the configured, empty database and store. Returns the differences."""
    problems = verify(source)
    if problems:
        return [f"checksum: {name}" for name in problems]
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            existing: int = connection.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            ).scalar_one()
        if existing:
            return ["target database is not empty"]
        url, env = _libpq(settings.database_url)
        subprocess.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--single-transaction",
                f"--dbname={url}",
                str(source / "database.dump"),
            ],
            check=True,
            env=env,
        )
        store = build_store(settings)
        objects = source / "objects"
        for path in sorted(objects.rglob("*")) if objects.exists() else []:
            if path.is_file():
                store.put(str(path.relative_to(objects)), path.read_bytes())
        with engine.connect() as connection:
            restored = fingerprint(connection, store)
    finally:
        engine.dispose()
    expected = manifest["fingerprint"]
    differences = [
        f"{key}: expected {expected.get(key)!r}, restored {restored.get(key)!r}"
        for key in sorted(set(expected) | set(restored))
        if expected.get(key) != restored.get(key)
    ]
    for key in ("entity_hash_errors", "object_errors"):
        if restored[key]:
            differences.append(f"{key}: {restored[key]}")
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup").add_argument("destination", type=Path)
    commands.add_parser("verify").add_argument("backup", type=Path)
    commands.add_parser("restore").add_argument("backup", type=Path)
    commands.add_parser("fingerprint")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.command == "backup":
        print(backup(settings, args.destination))
        return 0
    if args.command == "verify":
        problems = verify(args.backup)
    elif args.command == "restore":
        problems = restore(settings, args.backup)
    else:
        engine = create_engine(settings.database_url)
        with engine.connect() as connection:
            print(json.dumps(fingerprint(connection, build_store(settings)), indent=2))
        return 0
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
