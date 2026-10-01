"""P4 acceptance: the /v1 HTTP contract against PostgreSQL and the real worker."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sequence_vault.adapters.contracts import schema_errors
from sequence_vault.adapters.persistence.admin import Provisioning
from sequence_vault.api.app import create_app
from sequence_vault.application.authorization import Role
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
        if method in {"POST", "PUT", "PATCH"}:
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
    assert "attachment" in exported.headers["Content-Disposition"]
    assert_error(api.call("GET", f"/v1/records/{record_id}/export"), 400, "malformed_request")
    original = api.call("GET", f"/v1/files/{job['file_id']}/content")
    assert original.content.startswith(b">A1 heavy")


def test_identity_and_request_hygiene(api: Api) -> None:
    assert_error(api.call("GET", "/v1/me", user=None), 401, "unauthenticated")
    assert_error(api.call("GET", "/v1/me", user="mallory"), 403, "user_not_provisioned")
    no_csrf = api.client.post("/v1/uploads", headers={"X-Dev-User": "alice"}, json={})
    assert_error(no_csrf, 403, "csrf_header_missing")
    assert api.call("GET", "/v1/health", user=None).json() == {"status": "ok", "dev_login": True}


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
                "file_name": "scan.pdf",
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
    forged = api.client.get(
        "/v1/me", headers={"X-Forwarded-Email": "alice", "X-Proxy-Secret": "guess"}
    )
    assert_error(forged, 401, "unauthenticated")
    dev = api.client.get("/v1/me", headers={"X-Dev-User": "alice"})
    assert_error(dev, 401, "unauthenticated")
