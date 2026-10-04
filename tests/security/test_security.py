"""Security and adversarial cases (tests/security/README.md, T13, T15, T18)."""

import hashlib
import io
import json
import logging
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from sequence_vault.adapters.parsers.sandbox import SandboxedParser
from sequence_vault.adapters.persistence import tables as t
from sequence_vault.adapters.persistence.admin import Provisioning
from sequence_vault.adapters.security.clamd import EICAR
from sequence_vault.adapters.security.filetype import ContentTypeDetector
from sequence_vault.application.authorization import Role
from sequence_vault.observability import JsonFormatter, redact
from tests.integration.test_api import Api, assert_error

SEQUENCE = "EVQLVESGGGLVQPGGSLRLSCAASGFTFS"


@pytest.fixture
def api(engine: Engine, tmp_path: Path) -> Api:
    return Api(engine, tmp_path)


def committed(api: Api, name: str = "Secret") -> tuple[str, str, str]:
    """Upload, approve and commit one record as alice; returns task, candidate and record ids."""
    task_id = api.upload(f"{name}.fasta", f">{name}\n{SEQUENCE}\n".encode())
    cid = api.call("GET", f"/v1/jobs/{task_id}/candidates").json()["items"][0]["candidate"][
        "candidate_id"
    ]
    api.call(
        "POST", "/v1/reviews", json={"candidate_id": cid, "revision": 1, "decision": "approved"}
    )
    api.call(
        "POST",
        "/v1/commits",
        json={"items": [{"candidate_id": cid, "revision": 1}]},
        headers={"Idempotency-Key": "k"},
    )
    record_id = api.call("GET", "/v1/records").json()["items"][0]["record_id"]
    return task_id, cid, record_id


def test_other_tenants_see_nothing(api: Api, engine: Engine) -> None:
    task_id, cid, record_id = committed(api)
    job = api.call("GET", f"/v1/jobs/{task_id}").json()
    admin = Provisioning(engine)
    other_tenant = admin.tenant("Other company")
    other_project = admin.project(other_tenant, "Theirs")
    mallory = admin.user(other_tenant, "mallory", "Mallory")
    for role in Role:
        admin.grant(other_project, mallory, role)
    reads = [
        f"/v1/jobs/{task_id}",
        f"/v1/jobs/{task_id}/candidates",
        f"/v1/jobs/{task_id}/document",
        f"/v1/candidates/{cid}",
        f"/v1/records/{record_id}",
        f"/v1/records/{record_id}/export?version=1",
        f"/v1/files/{job['file_id']}/content",
    ]
    for path in reads:
        assert_error(api.call("GET", path, user="mallory"), 404, "not_found")
    assert (
        api.call("GET", "/v1/records", user="mallory", params={"sequence": SEQUENCE}).json()[
            "items"
        ]
        == []
    )
    writes = [
        ("PATCH", f"/v1/candidates/{cid}", {"name": "x"}, {"If-Match": '"2"'}),
        ("POST", "/v1/reviews", {"candidate_id": cid, "revision": 1, "decision": "rejected"}, {}),
        ("POST", f"/v1/jobs/{task_id}/reprocess", None, {}),
        ("POST", f"/v1/jobs/{task_id}/cancel", None, {}),
    ]
    for method, path, body, headers in writes:
        assert_error(
            api.call(method, path, user="mallory", json=body, headers=headers), 404, "not_found"
        )
    outcome = api.call(
        "POST",
        "/v1/commits",
        user="mallory",
        json={"items": [{"candidate_id": cid, "revision": 1}]},
        headers={"Idempotency-Key": "m"},
    )
    assert outcome.json()["results"][0]["status"] in {"FAILED", "ALREADY_COMMITTED"}
    assert outcome.json()["results"][0]["status"] == "FAILED"


def test_uploaded_names_never_become_paths(api: Api, engine: Engine) -> None:
    data = b">A\nMKTAYIAKQR\n"
    response = api.call(
        "POST",
        "/v1/uploads",
        json={
            "project_id": api.project,
            "file_name": "..\\..\\etc/passwd.fasta",
            "byte_count": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    assert response.json()["file_name"] == "passwd.fasta"
    with engine.connect() as c:
        key: str = c.execute(select(t.source_file.c.object_key)).scalar_one()
    assert "passwd" not in key and ".." not in key
    assert_error(
        api.call(
            "POST",
            "/v1/uploads",
            json={
                "project_id": api.project,
                "file_name": "bad\x00name.fasta",
                "byte_count": 4,
                "sha256": "a" * 64,
            },
        ),
        422,
        "invalid_file_name",
    )


def test_infected_originals_cannot_be_downloaded(api: Api) -> None:
    task_id = api.upload("virus.fasta", b">A\n" + EICAR)
    job = api.call("GET", f"/v1/jobs/{task_id}").json()
    assert (job["status"], job["failure_code"], job["security_status"]) == (
        "FAILED",
        "infected",
        "infected",
    )
    assert_error(api.call("GET", f"/v1/files/{job['file_id']}/content"), 404, "not_found")


def test_parser_sandbox_gets_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def capture(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(command=command, env=options["env"])
        return subprocess.CompletedProcess(command, 0, b'{"blocks": []}', b"")

    monkeypatch.setenv("SEQUENCE_VAULT_DATABASE_URL", "postgresql://user:secret@db/x")
    monkeypatch.setenv("SEQUENCE_VAULT_AI_API_KEY", "sk-secret")
    monkeypatch.setattr(subprocess, "run", capture)
    SandboxedParser().parse("fasta", b">A\n", file_id="f", run_id="r", parse_options={})
    assert "-I" in seen["command"]
    assert seen["command"][:2] == ["unshare", "-rn"] or not SandboxedParser().isolate_network
    assert set(seen["env"]) == {"PYTHONDONTWRITEBYTECODE", "LANG"}


def test_sandbox_cannot_write_file_content(tmp_path: Path) -> None:
    """RLIMIT_FSIZE=0 stops writes (CPython ignores SIGXFSZ, so the write fails quietly).
    Creating an empty file is still possible at this level; ADR 0003 level 2 removes it."""
    import sys

    target = tmp_path / "escape.txt"
    probe = (
        "import resource; resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0)); "
        f"f = open({str(target)!r}, 'w'); f.write('x' * 10000); f.close()"
    )
    subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, env={})
    assert not target.exists() or target.stat().st_size == 0


def test_sandbox_has_no_network_when_the_host_allows_it() -> None:
    import socket
    import sys

    from sequence_vault.adapters.parsers.sandbox import network_namespace_available

    if not network_namespace_available():
        pytest.skip("user namespaces are not permitted on this host")
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        probe = f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=2)"
        outside = subprocess.run([sys.executable, "-c", probe], capture_output=True)
        inside = subprocess.run(
            ["unshare", "-rn", sys.executable, "-c", probe], capture_output=True
        )
    assert outside.returncode == 0
    assert inside.returncode != 0
    assert SandboxedParser().isolate_network


@pytest.mark.parametrize("name", ["bomb.docx", "bomb.xlsx"])
def test_archive_bombs_are_refused(name: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", b"\0" * 300_000_000)
    assert ContentTypeDetector().detect(buffer.getvalue(), name).reason == "decompression_limit"


def test_sequences_never_reach_logs(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    formatter = JsonFormatter()
    logger = logging.getLogger("sequence_vault.test")
    try:
        raise ValueError(f"constraint failed for {SEQUENCE.lower()} and {SEQUENCE}")
    except ValueError:
        logger.exception("insert failed for MKTAYIAKQR QISFVKSHFS RQLEERLGLI")
    line = json.loads(formatter.format(caplog.records[-1]))
    assert SEQUENCE not in json.dumps(line) and SEQUENCE.lower() not in json.dumps(line)
    assert "residues redacted" in line["message"] and "residues redacted" in line["exception"]
    assert redact("task_1f2e3d failed with code scan_unavailable") == (
        "task_1f2e3d failed with code scan_unavailable"
    )
