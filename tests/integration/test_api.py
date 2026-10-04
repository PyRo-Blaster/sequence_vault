"""P4 acceptance: the /v1 HTTP contract against PostgreSQL and the real worker."""

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sequence_vault.adapters.contracts import schema_errors
from sequence_vault.adapters.persistence.admin import Provisioning, SqlProjectAdmin
from sequence_vault.api.app import create_app
from sequence_vault.application.authorization import Actor, Role
from sequence_vault.application.legacy_migration import LegacyMigration
from sequence_vault.entrypoints.bootstrap import api_services, build
from sequence_vault.settings import REPO_ROOT, Settings
from sequence_vault.workers.worker import Worker

CONTRACTS = REPO_ROOT / "packages/contracts"
WRITE = {"X-Requested-With": "sequence-vault"}


class Api:
    def __init__(self, engine: Engine, tmp_path: Path, **extra: str) -> None:
        environ = {
            "SEQUENCE_VAULT_ENV": "development",
            "SEQUENCE_VAULT_STORAGE": "local",
            "SEQUENCE_VAULT_LOCAL_STORAGE_DIR": str(tmp_path / "objects"),
            "SEQUENCE_VAULT_SCANNER": "development",
            "SEQUENCE_VAULT_DEV_LOGIN": "true",
            **extra,
        }
        self.container = build(Settings.from_env(environ), engine=engine)
        self.client = TestClient(create_app(api_services(self.container)))
        self.worker = Worker(
            self.container.queue, self.container.pipeline, worker_id="w", delay=lambda _: 0
        )
        admin = Provisioning(engine)
        tenant = admin.tenant("Dept")
        self.tenant = tenant
        self.project = admin.project(tenant, "Antibodies")
        self.other_project = admin.project(tenant, "Enzymes")
        for subject, roles, project in (
            ("alice", [Role.UPLOADER, Role.REVIEWER], self.project),
            ("victor", [Role.VIEWER], self.project),
            ("olga", [Role.UPLOADER, Role.REVIEWER], self.other_project),
        ):
            user_id = admin.user(tenant, subject, subject.title())
            for role in roles:
                admin.grant(project, user_id, role)

    def call(self, method: str, path: str, user: str | None = "alice", **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if user:
            headers["X-Dev-User"] = user
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            headers = {**WRITE, **headers}
        return self.client.request(method, path, headers=headers, **kwargs)

    def upload(
        self, name: str, data: bytes, user: str = "alice", project: str | None = None
    ) -> str:
        declared = self.call(
            "POST",
            "/v1/uploads",
            user,
            json={
                "project_id": project or self.project,
                "file_name": name,
                "byte_count": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
        assert declared.status_code == 201, declared.text
        file_id = declared.json()["file_id"]
        put = self.call("PUT", f"/v1/uploads/{file_id}/content", user, content=data)
        assert put.status_code == 204, put.text
        done = self.call("POST", f"/v1/uploads/{file_id}/complete", user)
        assert done.status_code == 202, done.text
        self.worker.run_until_idle()
        return str(done.json()["task_id"])


@pytest.fixture
def api(engine: Engine, tmp_path: Path) -> Api:
    return Api(engine, tmp_path)


def assert_error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert set(body) == {"code", "message", "request_id", "details", "retryable"}


def test_full_fasta_journey_over_http(api: Api) -> None:
    me = api.call("GET", "/v1/me").json()
    assert [p["name"] for p in me["projects"]] == ["Antibodies"]
    assert ".fasta" in me["accepted_extensions"]

    task_id = api.upload("batch.fasta", b">A1 heavy\nmktayiakqr\n>A2\nMKTAYIAKQW\n")
    job = api.call("GET", f"/v1/jobs/{task_id}").json()
    assert "tenant_id" not in job
    assert (job["status"], job["candidate_counts"]) == ("REVIEW_READY", {"NEEDS_REVIEW": 2})
    listed = api.call("GET", "/v1/jobs", params={"project_id": api.project}).json()
    assert [item["task_id"] for item in listed["items"]] == [task_id]

    items = api.call("GET", f"/v1/jobs/{task_id}/candidates").json()["items"]
    for item in items:
        assert schema_errors(CONTRACTS, "candidate", item["candidate"]) == []
    first = items[0]["candidate"]
    assert first["normalized_sequence"] == "MKTAYIAKQR"
    assert [log["operation"] for log in first["transformation_log"]] == ["uppercase"]
    document = api.call("GET", f"/v1/jobs/{task_id}/document").json()
    assert document["offset_unit"] == "unicode_codepoint"
    assert {b["block_id"] for b in document["blocks"]} >= {"h0", "s0", "h1", "s1"}

    cid = first["candidate_id"]
    renamed = api.call(
        "PATCH",
        f"/v1/candidates/{cid}",
        json={"name": "A1 heavy chain"},
        headers={"If-Match": '"1"'},
    )
    assert renamed.status_code == 200 and renamed.headers["ETag"] == '"2"'
    stale = api.call(
        "PATCH", f"/v1/candidates/{cid}", json={"name": "late"}, headers={"If-Match": '"1"'}
    )
    assert_error(stale, 409, "revision_conflict")

    for candidate_id, revision in ((cid, 2), (items[1]["candidate"]["candidate_id"], 1)):
        reviewed = api.call(
            "POST",
            "/v1/reviews",
            json={"candidate_id": candidate_id, "revision": revision, "decision": "approved"},
        )
        assert reviewed.json()["candidate"]["status"] == "APPROVED"
    body = {
        "items": [
            {"candidate_id": cid, "revision": 2},
            {"candidate_id": items[1]["candidate"]["candidate_id"], "revision": 1},
        ]
    }
    committed = api.call("POST", "/v1/commits", json=body, headers={"Idempotency-Key": "batch-1"})
    assert committed.json()["counts"] == {"COMMITTED": 2}
    again = api.call("POST", "/v1/commits", json=body, headers={"Idempotency-Key": "batch-1"})
    assert again.json()["results"] == committed.json()["results"]
    assert api.call("GET", f"/v1/jobs/{task_id}").json()["status"] == "COMPLETED"

    by_name = api.call("GET", "/v1/records", params={"q": "heavy"}).json()["items"]
    assert [r["name"] for r in by_name] == ["A1 heavy chain"]
    by_sequence = api.call("GET", "/v1/records", params={"sequence": "mktay iakqw\n"}).json()
    assert [r["name"] for r in by_sequence["items"]] == ["A2"]
    record_id = by_name[0]["record_id"]
    record = api.call("GET", f"/v1/records/{record_id}").json()
    (version,) = record["versions"]
    (provenance,) = version["provenance"]
    assert (provenance["file_name"], provenance["approved_by"]) == ("batch.fasta", "Alice")
    assert provenance["transformation_log"][0]["operation"] == "uppercase"
    exported = api.call("GET", f"/v1/records/{record_id}/export", params={"version": 1})
    assert exported.text == f">A1_heavy_chain record={record_id} version=1\nMKTAYIAKQR\n"
    assert exported.headers["Content-Disposition"] == (
        'attachment; filename="A1_heavy_chain_v1.fasta"; '
        "filename*=UTF-8''A1%20heavy%20chain_v1.fasta"
    )
    assert_error(api.call("GET", f"/v1/records/{record_id}/export"), 400, "malformed_request")
    original = api.call("GET", f"/v1/files/{job['file_id']}/content")
    assert original.content.startswith(b">A1 heavy")


def test_upload_content_cannot_change_after_completion(api: Api, engine: Engine) -> None:
    """Only the declared bytes are stored, and nothing is accepted after /complete (B1)."""
    good, swapped = b">A\nMKTAYIAKQR\n", b">A\nMKTAYIAKQW\n"
    admin = Provisioning(engine)
    admin.grant(api.project, admin.user(api.tenant, "uma", "Uma"), Role.UPLOADER)
    declared = api.call(
        "POST",
        "/v1/uploads",
        json={
            "project_id": api.project,
            "file_name": "a.fasta",
            "byte_count": len(good),
            "sha256": hashlib.sha256(good).hexdigest(),
        },
    )
    file_id = declared.json()["file_id"]
    content = f"/v1/uploads/{file_id}/content"
    assert_error(api.call("PUT", content, content=swapped), 422, "checksum_mismatch")
    assert api.call("PUT", content, content=good).status_code == 204
    assert api.call("POST", f"/v1/uploads/{file_id}/complete").status_code == 202
    assert_error(api.call("PUT", content, "uma", content=swapped), 409, "upload_complete")
    assert_error(api.call("PUT", content, content=good), 409, "upload_complete")
    api.worker.run_until_idle()
    assert api.call("GET", f"/v1/files/{file_id}/content").content == good


def test_legacy_candidates_match_the_candidate_contract(api: Api, engine: Engine) -> None:
    """Legacy candidates omit extraction_record_index instead of sending null."""
    c = api.container
    migration = LegacyMigration(
        c.uow,
        c.store,
        c.scanner,
        c.registry,
        max_residues=c.policy.limits.max_residues_per_sequence,
    )
    alice = SqlProjectAdmin(engine).user_in_tenant(api.tenant, "alice")
    assert alice is not None
    export = json.dumps(
        {
            "source_system": "LIMS",
            "records": [
                {"legacy_id": "L-1", "project": "Old", "name": "B", "sequence": "MKT4AYIAKQ"}
            ],
        }
    ).encode()
    report = migration.run(
        Actor(alice, api.tenant), api.project, "e.json", export, "Old", dry_run=False
    )
    (pending,) = report["pending_review"]
    body = api.call("GET", f"/v1/candidates/{pending['candidate_id']}").json()
    assert "extraction_record_index" not in body["candidate"]
    assert schema_errors(CONTRACTS, "candidate", body["candidate"]) == []


def test_identity_and_request_hygiene(api: Api) -> None:
    assert_error(api.call("GET", "/v1/me", user=None), 401, "unauthenticated")
    assert_error(api.call("GET", "/v1/me", user="mallory"), 403, "user_not_provisioned")
    no_csrf = api.client.post("/v1/uploads", headers={"X-Dev-User": "alice"}, json={})
    assert_error(no_csrf, 403, "csrf_header_missing")
    assert api.call("GET", "/v1/health", user=None).json() == {"status": "ok", "dev_login": True}
    # Sign-in names are matched without regard to case (B8).
    assert api.call("GET", "/v1/me", user="ALICE").status_code == 200


def test_commit_preview_separates_new_records_from_sequence_reuse(api: Api) -> None:
    """B16: a new name with a stored sequence is a new record that reuses the sequence."""
    first = api.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    (envelope,) = api.call("GET", f"/v1/jobs/{first}/candidates").json()["items"]
    cid = envelope["candidate"]["candidate_id"]
    api.call(
        "POST", "/v1/reviews", json={"candidate_id": cid, "revision": 1, "decision": "approved"}
    )
    body = {"items": [{"candidate_id": cid, "revision": 1}]}
    committed = api.call("POST", "/v1/commits", json=body, headers={"Idempotency-Key": "p"})
    assert committed.json()["counts"] == {"COMMITTED": 1}

    batch = b">B\nMKTAYIAKQR\n>C\nMKTAYIAKQW\n>A\nMKTAYIAKQR\n>D\nMKTAYIAKQW\n"
    second = api.upload("b.fasta", batch)
    ids = [
        e["candidate"]["candidate_id"]
        for e in api.call("GET", f"/v1/jobs/{second}/candidates").json()["items"]
    ]
    preview = api.call("POST", "/v1/commits/preview", json={"candidate_ids": [*ids, "cand_x"]})
    assert preview.status_code == 200, preview.text
    assert [(p["record_action"], p["reuses_sequence"]) for p in preview.json()["items"]] == [
        ("create_record", True),  # B: stored sequence, new name
        ("create_record", False),  # C: new sequence
        ("add_provenance", True),  # A: same name, same sequence
        ("create_record", True),  # D: C's sequence, committed earlier in the batch
        (None, False),  # not visible
    ]
    hidden = api.call("POST", "/v1/commits/preview", user="olga", json={"candidate_ids": ids})
    assert {p["record_action"] for p in hidden.json()["items"]} == {None}


def test_downloads_keep_unicode_file_names(api: Api) -> None:
    """Content-Disposition carries an ASCII fallback and the UTF-8 name (B7)."""
    task_id = api.upload("抗体 序列.fasta", ">抗体 A\nMKTAYIAKQR\n".encode())
    file_id = api.call("GET", f"/v1/jobs/{task_id}").json()["file_id"]
    original = api.call("GET", f"/v1/files/{file_id}/content")
    assert original.headers["Content-Disposition"] == (
        'attachment; filename="_____.fasta"; '
        "filename*=UTF-8''%E6%8A%97%E4%BD%93%20%E5%BA%8F%E5%88%97.fasta"
    )


def test_api_docs_are_served_only_in_development(api: Api) -> None:
    """The schema and the interactive docs are not published outside development (B10)."""
    assert api.call("GET", "/openapi.json", user=None).status_code == 200
    services = api_services(api.container)
    production = dataclasses.replace(
        services, settings=dataclasses.replace(services.settings, env="production")
    )
    client = TestClient(create_app(production))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_error_codes_follow_the_contract(api: Api) -> None:
    task_id = api.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    cid = api.call("GET", f"/v1/jobs/{task_id}/candidates").json()["items"][0]["candidate"][
        "candidate_id"
    ]
    assert_error(
        api.call(
            "POST",
            "/v1/reviews",
            user="victor",
            json={"candidate_id": cid, "revision": 1, "decision": "approved"},
        ),
        403,
        "forbidden",
    )
    assert_error(api.call("GET", f"/v1/jobs/{task_id}", user="olga"), 404, "not_found")
    assert_error(
        api.call("POST", "/v1/reviews", json={"candidate_id": cid}), 400, "malformed_request"
    )
    assert_error(
        api.call(
            "POST",
            "/v1/uploads",
            json={
                "project_id": api.project,
                "file_name": "huge.fasta",
                "byte_count": 10**9,
                "sha256": "a" * 64,
            },
        ),
        413,
        "file_too_large",
    )
    assert_error(
        api.call(
            "POST",
            "/v1/uploads",
            json={
                "project_id": api.project,
                "file_name": "scan.png",
                "byte_count": 10,
                "sha256": "a" * 64,
            },
        ),
        422,
        "unsupported_format",
    )
    assert_error(
        api.call("PATCH", f"/v1/candidates/{cid}", json={"name": "x"}), 428, "revision_required"
    )
    assert_error(
        api.call("POST", "/v1/commits", json={"items": [{"candidate_id": cid, "revision": 1}]}),
        400,
        "idempotency_key_required",
    )
    assert_error(
        api.call("POST", "/v1/candidates/missing/archive", json={"revision": 1}), 404, "not_found"
    )
    assert_error(
        api.call("GET", "/v1/jobs", params={"project_id": api.project, "cursor": "%%%"}),
        400,
        "malformed_request",
    )


def test_records_never_leak_across_projects(api: Api) -> None:
    task_id = api.upload("Secret.fasta", b">Secret\nMKTAYIAKQR\n")
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
    assert api.call("GET", "/v1/records", user="olga").json()["items"] == []
    found = api.call("GET", "/v1/records", user="olga", params={"sequence": "MKTAYIAKQR"})
    assert found.json()["items"] == []
    assert_error(api.call("GET", f"/v1/records/{record_id}", user="olga"), 404, "not_found")
    assert_error(
        api.call("GET", "/v1/records", user="olga", params={"project_id": api.project}),
        404,
        "not_found",
    )
    assert api.call("GET", f"/v1/records/{record_id}", user="victor").status_code == 200


def test_fasta_export_neutralizes_header_injection(api: Api) -> None:
    task_id = api.upload("A.fasta", b">A\nMKTAYIAKQR\n")
    cid = api.call("GET", f"/v1/jobs/{task_id}/candidates").json()["items"][0]["candidate"][
        "candidate_id"
    ]
    api.call(
        "PATCH",
        f"/v1/candidates/{cid}",
        json={"name": "evil\n>INJECTED\nAAAA"},
        headers={"If-Match": '"1"'},
    )
    api.call(
        "POST", "/v1/reviews", json={"candidate_id": cid, "revision": 2, "decision": "approved"}
    )
    api.call(
        "POST",
        "/v1/commits",
        json={"items": [{"candidate_id": cid, "revision": 2}]},
        headers={"Idempotency-Key": "k"},
    )
    record_id = api.call("GET", "/v1/records").json()["items"][0]["record_id"]
    text = api.call("GET", f"/v1/records/{record_id}/export", params={"version": 1}).text
    assert text.count(">") == 1 and text.count("\n") == 2


def test_proxy_identity_requires_the_shared_secret(engine: Engine, tmp_path: Path) -> None:
    api = Api(
        engine, tmp_path, SEQUENCE_VAULT_DEV_LOGIN="false", SEQUENCE_VAULT_PROXY_SECRET="s3cret"
    )
    ok = api.client.get(
        "/v1/me", headers={"X-Forwarded-Email": "alice", "X-Proxy-Secret": "s3cret"}
    )
    assert ok.status_code == 200
    upper = api.client.get(
        "/v1/me", headers={"X-Forwarded-Email": "Alice", "X-Proxy-Secret": "s3cret"}
    )
    assert upper.status_code == 200
    forged = api.client.get(
        "/v1/me", headers={"X-Forwarded-Email": "alice", "X-Proxy-Secret": "guess"}
    )
    assert_error(forged, 401, "unauthenticated")
    dev = api.client.get("/v1/me", headers={"X-Dev-User": "alice"})
    assert_error(dev, 401, "unauthenticated")
