"""Project administration and the quality summary over HTTP."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.adapters.persistence.admin import Provisioning
from sequence_vault.application.authorization import Role
from sequence_vault.entrypoints.admin import main as admin_cli
from tests.integration.test_api import Api, assert_error


@pytest.fixture
def api(engine: Engine, tmp_path: Path) -> Api:
    api = Api(engine, tmp_path)
    admin = Provisioning(engine)
    tenant = admin.tenant("Dept")
    boss = admin.user(tenant, "boss", "Boss")
    admin.grant(api.project, boss, Role.PROJECT_ADMIN)
    admin.user(tenant, "newcomer", "Newcomer")
    return api


def roles(response: object, subject: str) -> list[str]:
    items = response.json()["items"]  # type: ignore[attr-defined]
    return next((m["roles"] for m in items if m["subject"] == subject), [])


def test_project_admins_manage_roles_with_an_audit_trail(api: Api, engine: Engine) -> None:
    path = f"/v1/projects/{api.project}/members"
    assert roles(api.call("GET", path, user="boss"), "alice") == ["reviewer", "uploader"]
    granted = api.call("POST", path, user="boss", json={"subject": "newcomer", "role": "viewer"})
    assert roles(granted, "newcomer") == ["viewer"]
    newcomer = next(m["user_id"] for m in granted.json()["items"] if m["subject"] == "newcomer")
    revoked = api.call("DELETE", f"{path}/{newcomer}/roles/viewer", user="boss")
    assert roles(revoked, "newcomer") == []
    with engine.connect() as c:
        events = c.execute(
            select(t.audit_event.c.event, t.audit_event.c.actor_id)
            .where(t.audit_event.c.event.like("member.%"))
            .order_by(t.audit_event.c.id)
        ).all()
    assert [e for e, _ in events][-2:] == ["member.granted", "member.revoked"]
    assert all(actor is not None for _, actor in events[-2:])


def test_only_admins_manage_and_the_last_admin_stays(api: Api) -> None:
    path = f"/v1/projects/{api.project}/members"
    assert_error(api.call("GET", path, user="alice"), 403, "forbidden")
    assert_error(
        api.call("POST", path, user="alice", json={"subject": "newcomer", "role": "reviewer"}),
        403,
        "forbidden",
    )
    assert_error(api.call("GET", path, user="olga"), 404, "not_found")
    assert_error(
        api.call("POST", path, user="boss", json={"subject": "ghost", "role": "viewer"}),
        422,
        "unknown_user",
    )
    boss = next(
        m["user_id"]
        for m in api.call("GET", path, user="boss").json()["items"]
        if m["subject"] == "boss"
    )
    assert_error(
        api.call("DELETE", f"{path}/{boss}/roles/project_admin", user="boss"), 409, "last_admin"
    )


def test_quality_summary_counts_outcomes(api: Api) -> None:
    task_id = api.upload("a.fasta", b">A\nmktayiakqr\n>B\nMKT1AYIAKQR\n")
    items = api.call("GET", f"/v1/jobs/{task_id}/candidates").json()["items"]
    first = items[0]["candidate"]["candidate_id"]
    api.call(
        "PATCH", f"/v1/candidates/{first}", json={"name": "A renamed"}, headers={"If-Match": '"1"'}
    )
    second = items[1]["candidate"]["candidate_id"]
    api.call(
        "PATCH",
        f"/v1/candidates/{second}",
        json={"sequence": {"typed_sequence": "MKTAYIAKQR", "reason": "Removed the digit"}},
        headers={"If-Match": '"1"'},
    )
    api.call(
        "POST", "/v1/reviews", json={"candidate_id": second, "revision": 2, "decision": "approved"}
    )
    quality = api.call("GET", f"/v1/projects/{api.project}/quality", user="alice").json()
    assert quality["tasks"] == {"REVIEW_READY": 1}
    assert quality["candidates"] == {"NEEDS_REVIEW": 1, "APPROVED": 1}
    assert (quality["manual_revision_rate"], quality["rename_rate"]) == (1.0, 0.5)
    assert quality["formats"] == [{"format": "fasta", "tasks": 1, "failed": 0, "failure_rate": 0.0}]
    assert quality["runs"][0]["parser_version"] == "fasta-1"
    assert_error(
        api.call("GET", f"/v1/projects/{api.project}/quality", user="victor"), 403, "forbidden"
    )


def test_admin_cli_reports_unknown_ids_without_a_traceback(
    api: Api, database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B10: a mistyped ID is an error message and exit status 2, not a stack trace."""
    monkeypatch.setenv("SEQUENCE_VAULT_DATABASE_URL", database_url)
    grant = ["grant", "--user", "user_missing", "--role", "viewer"]
    assert admin_cli([*grant, "--project", "proj_missing"]) == 2
    assert capsys.readouterr().err == "error: no such project\n"
    assert admin_cli([*grant, "--project", api.project]) == 2
    assert capsys.readouterr().err.startswith("error: unknown tenant, project or user (")
    assert (
        admin_cli(["add-user", "--tenant", "tenant_missing", "--subject", "x", "--name", "X"]) == 2
    )
    assert "Traceback" not in capsys.readouterr().err
