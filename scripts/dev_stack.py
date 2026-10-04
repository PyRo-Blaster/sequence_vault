"""Run a complete development backend: PostgreSQL, migrations, seed users, API and worker.

Uses SEQUENCE_VAULT_DATABASE_URL when set; otherwise starts a throwaway local PostgreSQL
cluster (deleted on exit). Storage is local and the scanner is the development scanner.
With SEQUENCE_VAULT_DEV_STATE=path, writes the database URL, storage directory and seeded
IDs there as JSON for end-to-end tests.

    uv run python scripts/dev_stack.py
"""

import json
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


def _terminated(signum: int, _frame: object) -> None:
    # Once only: `uv run` forwards SIGTERM and the process group receives it too, and a
    # second exception would abort the cleanup in main's finally.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def main() -> int:
    # SIGTERM (Playwright's graceful shutdown, docker stop) and SIGHUP unwind through the
    # finally below, so a throwaway cluster never outlives the stack.
    signal.signal(signal.SIGTERM, _terminated)
    signal.signal(signal.SIGHUP, _terminated)
    server: subprocess.Popen[bytes] | None = None
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
        seeded = subprocess.run(
            [*python, "sequence_vault.entrypoints.admin", "seed-dev"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        print(seeded, end="")
        state = os.environ.get("SEQUENCE_VAULT_DEV_STATE")
        if state:
            # Lets end-to-end tests run operator tools against this throwaway stack.
            storage = Path(env.get("SEQUENCE_VAULT_LOCAL_STORAGE_DIR", ".local/objects"))
            Path(state).write_text(
                json.dumps(
                    {
                        **json.loads(seeded),
                        "database_url": env["SEQUENCE_VAULT_DATABASE_URL"],
                        "local_storage_dir": str(storage.resolve()),
                    }
                )
            )
        server = subprocess.Popen([*python, "sequence_vault.entrypoints.dev_server"], env=env)
        return server.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signum, signal.SIG_IGN)
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
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
