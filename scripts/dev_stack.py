"""Run a complete development backend: PostgreSQL, migrations, seed users, API and worker.

Uses SEQUENCE_VAULT_DATABASE_URL when set; otherwise starts a throwaway local PostgreSQL
cluster (deleted on exit). Storage is local and the scanner is the development scanner.

    uv run python scripts/dev_stack.py
"""

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def postgres_bin() -> Path:
    found = sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)
    pg_ctl = shutil.which("pg_ctl")
    if pg_ctl:
        found.insert(0, Path(pg_ctl).parent)
    for path in found:
        if (path / "initdb").exists():
            return path
    raise SystemExit("PostgreSQL server binaries not found; set SEQUENCE_VAULT_DATABASE_URL.")


def as_postgres(command: list[str]) -> list[str]:
    return ["runuser", "-u", "postgres", "--", *command] if os.geteuid() == 0 else command


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    env = dict(os.environ)
    env.setdefault("SEQUENCE_VAULT_ENV", "development")
    env.setdefault("SEQUENCE_VAULT_STORAGE", "local")
    env.setdefault("SEQUENCE_VAULT_SCANNER", "development")
    env.setdefault("SEQUENCE_VAULT_DEV_LOGIN", "true")
    workdir: Path | None = None
    bindir: Path | None = None
    if not env.get("SEQUENCE_VAULT_DATABASE_URL"):
        bindir = postgres_bin()
        workdir = Path(tempfile.mkdtemp(prefix="sv-dev-"))
        workdir.chmod(0o777)
        port = free_port()
        subprocess.run(
            as_postgres(
                [
                    str(bindir / "initdb"),
                    "-D",
                    str(workdir / "data"),
                    "-A",
                    "trust",
                    "-U",
                    "postgres",
                ]
            ),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            as_postgres(
                [
                    str(bindir / "pg_ctl"),
                    "-D",
                    str(workdir / "data"),
                    "-l",
                    str(workdir / "server.log"),
                    "-o",
                    f"-p {port} -k {workdir} -c listen_addresses=127.0.0.1",
                    "-w",
                    "start",
                ]
            ),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        env["SEQUENCE_VAULT_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"
        )
        env.setdefault("SEQUENCE_VAULT_LOCAL_STORAGE_DIR", str(workdir / "objects"))
    python = [sys.executable, "-m"]
    try:
        subprocess.run(
            [*python, "sequence_vault.entrypoints.admin", "migrate"], env=env, check=True
        )
        subprocess.run(
            [*python, "sequence_vault.entrypoints.admin", "seed-dev"], env=env, check=True
        )
        server = subprocess.Popen([*python, "sequence_vault.entrypoints.dev_server"], env=env)
        signal.signal(signal.SIGTERM, lambda *_: server.terminate())
        return server.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if workdir is not None and bindir is not None:
            subprocess.run(
                as_postgres(
                    [str(bindir / "pg_ctl"), "-D", str(workdir / "data"), "-m", "immediate", "stop"]
                ),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
