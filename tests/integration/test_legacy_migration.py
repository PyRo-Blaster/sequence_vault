"""P7 legacy migration: snapshot, same QC, clean rows committed, anomalies to review,
reconciliation (design, "Legacy System Migration")."""

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.application.authorization import Actor
from sequence_vault.application.commit import CommitItem, CommitStatus
from sequence_vault.application.errors import Forbidden, InvalidRequest, NotFound
from sequence_vault.application.legacy_migration import LegacyMigration
from sequence_vault.domain.candidate import CandidateStatus
from sequence_vault.domain.task import TaskStatus
from sequence_vault.settings import REPO_ROOT
from tests.integration.test_pipeline import Env

PROTEIN_A = "MKTAYIAKQRQISFVKSHFSRQ"
PROTEIN_B = "MSDNELQKAFEELGKRAAELGG"


def export(records: list[dict[str, Any]], permissions: list[dict[str, str]] | None = None) -> bytes:
    return json.dumps(
        {
            "source_system": "LIMS",
            "exported_at": "2026-09-20T10:00:00+00:00",
            "records": [{"project": "Antibodies", **record} for record in records],
            "permissions": permissions or [],
        }
    ).encode()


ROWS: list[dict[str, Any]] = [
    {
        "legacy_id": "L-1",
        "name": "Ab-1",
        "sequence": PROTEIN_A,
        "created_at": "2019-01-01T00:00:00+00:00",
    },
    # Same sequence under another name: entity reuse is information, not a problem.
    {
        "legacy_id": "L-2",
        "name": "Ab-2",
        "sequence": PROTEIN_A.lower(),
        "created_at": "2019-02-01T00:00:00+00:00",
    },
    # A later edit of Ab-1 in the legacy system: needs a version decision.
    {
        "legacy_id": "L-3",
        "name": "Ab-1",
        "sequence": PROTEIN_B,
        "created_at": "2019-03-01T00:00:00+00:00",
    },
    {"legacy_id": "L-4", "name": "Bad", "sequence": "MKT4AYIAKQ", "created_at": None},
    {"legacy_id": "L-5", "name": "Primer", "sequence": "ATGCGTACGTTAGC", "molecule_type": "dna"},
    {"legacy_id": "L-6", "name": None, "sequence": PROTEIN_B[::-1]},
    {"legacy_id": None, "name": "Lost", "sequence": PROTEIN_A},
    {"legacy_id": "L-7", "name": "Dup", "sequence": PROTEIN_A},
    {"legacy_id": "L-7", "name": "Dup", "sequence": PROTEIN_B},
    {"legacy_id": "L-8", "name": "When", "sequence": PROTEIN_A, "created_at": "yesterday"},
    {"legacy_id": "X-1", "project": "Other", "name": "Elsewhere", "sequence": PROTEIN_A},
]


class Migration:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.service = LegacyMigration(
            env.app.uow,
            env.app.store,
            env.app.scanner,
            env.app.registry,
            max_residues=env.app.policy.limits.max_residues_per_sequence,
        )
        self.operator = env.world.user("operator", {env.project: ["uploader", "reviewer"]})

    def run(self, data: bytes, *, dry_run: bool = False, actor: Actor | None = None) -> Any:
        return self.service.run(
            actor or self.operator,
            self.env.project,
            "lims-export.json",
            data,
            "Antibodies",
            dry_run=dry_run,
        )


@pytest.fixture
def m(engine: Engine, tmp_path: Path) -> Migration:
    return Migration(Env(engine, tmp_path))


def count(engine: Engine, table: Any) -> int:
    with engine.connect() as c:
        return int(c.execute(select(func.count()).select_from(table)).scalar_one())


def by_legacy_id(report: dict[str, Any]) -> dict[str, list[str]]:
    return {item["legacy_id"]: item["rules"] for item in report["pending_review"]}


def test_a_dry_run_reports_without_writing(m: Migration, engine: Engine) -> None:
    report = m.run(export(ROWS), dry_run=True)

    assert report["dry_run"] and report["balanced"]
    assert report["counts"] == {
        "legacy_records": 10,
        "rejected": 4,
        "accepted": 6,
        "unchanged_since_last_import": 0,
        "committed": 2,
        "pending_review": 4,
        "closed_without_publishing": 0,
    }
    assert sorted((r["legacy_id"] or "", r["reason"]) for r in report["rejected"]) == [
        ("", "missing_legacy_id"),
        ("L-7", "duplicate_legacy_id"),
        ("L-7", "duplicate_legacy_id"),
        ("L-8", "invalid_timestamp"),
    ]
    pending = by_legacy_id(report)
    assert pending["L-3"] == ["QC09"]
    assert "QC03" in pending["L-4"] and "QC11" in pending["L-5"]
    assert report["unique_sequences"] == {"accepted": 5, "committed": 1}
    assert count(engine, t.candidate) == 0 and count(engine, t.source_file) == 0


def test_import_commits_clean_rows_and_routes_anomalies_to_review(
    m: Migration, engine: Engine
) -> None:
    permissions = [
        {"subject": "operator@corp", "project": "Antibodies", "role": "reviewer"},
        {"subject": "bob@corp", "project": "Antibodies", "role": "viewer"},
        {"subject": "carol@corp", "project": "Antibodies", "role": "superuser"},
    ]
    report = m.run(export(ROWS, permissions))

    assert report["balanced"] and report["hash_mismatches"] == []
    assert (report["counts"]["committed"], report["counts"]["pending_review"]) == (2, 4)
    assert set(by_legacy_id(report)) == {"L-3", "L-4", "L-5", "L-6"}
    assert report["permissions"] == {
        "legacy": 3,
        "matched": 1,
        "missing": [{"subject": "bob@corp", "role": "viewer"}],
        "unmapped_roles": [{"subject": "carol@corp", "role": "superuser"}],
        "only_in_new_system": [
            {"subject": "alice@corp", "role": "reviewer"},
            {"subject": "alice@corp", "role": "uploader"},
            {"subject": "operator@corp", "role": "uploader"},
        ],
    }
    with engine.connect() as c:
        records = c.execute(select(t.record.c.display_name).order_by(t.record.c.display_name))
        assert [r.display_name for r in records] == ["Ab-1", "Ab-2"]
        # One entity for the identical sequence, with the original names kept.
        assert count(engine, t.sequence_entity) == 1
        legacy = {r.legacy_id: r for r in c.execute(select(t.legacy_record))}
        assert set(legacy) == {"L-1", "L-2", "L-3", "L-4", "L-5", "L-6"}
        assert legacy["L-1"].legacy_created_at.year == 2019
        batch = c.execute(select(t.legacy_batch)).one()
        assert batch.report["counts"] == report["counts"] and batch.finished_at is not None
        snapshot = c.execute(select(t.source_file).where(t.source_file.c.id == batch.file_id)).one()
        assert snapshot.detected_type == "legacy_export" and snapshot.security_status == "clean"
        events = {r.event for r in c.execute(select(t.audit_event.c.event))}
    assert {"legacy.batch_started", "candidate.legacy_imported", "legacy.batch_finished"} <= events
    assert m.env.app.store.get(snapshot.object_key) == export(ROWS, permissions)

    with m.env.app.uow() as uow:
        rows = [uow.candidates.get(r.candidate_id) for r in legacy.values()]
        task = uow.tasks.get_by_file(batch.file_id)
    assert task is not None and task.task.status is TaskStatus.REVIEW_READY
    for row in rows:
        assert row is not None
        assert row.candidate.origin == "legacy_import" and row.candidate.spans == ()
        assert row.candidate.name is None or row.candidate.name.source == "legacy_import"
    assert rows[5] is not None and rows[5].candidate.status is CandidateStatus.NEEDS_REVIEW


def test_a_reimport_skips_unchanged_rows_and_brings_in_changes(
    m: Migration, engine: Engine
) -> None:
    m.run(export(ROWS))
    candidates = count(engine, t.candidate)

    again = m.run(export(ROWS))
    assert again["counts"]["unchanged_since_last_import"] == 6
    assert (again["counts"]["committed"], again["counts"]["pending_review"]) == (2, 4)
    assert count(engine, t.candidate) == candidates

    changed = [dict(row) for row in ROWS]
    changed[1]["sequence"] = PROTEIN_B + "K"
    later = m.run(export(changed))
    assert later["counts"]["unchanged_since_last_import"] == 5
    assert by_legacy_id(later)["L-2"] == ["QC09"]
    assert later["balanced"]


def test_review_completes_the_migration(m: Migration, engine: Engine) -> None:
    report = m.run(export(ROWS[:3]))
    candidate_id = report["pending_review"][0]["candidate_id"]
    reviewer = m.operator
    reviews = m.env.app.reviews
    row = reviews.resolve(reviewer, candidate_id, 1, "QC09", "create_new_version")
    reviews.decide(reviewer, candidate_id, row.candidate.revision, approve=True)
    [outcome] = m.env.app.commits.commit(
        reviewer, "review-1", [CommitItem(candidate_id, row.candidate.revision)]
    )
    assert outcome.status is CommitStatus.COMMITTED

    final = m.run(export(ROWS[:3]), dry_run=True)
    assert final["counts"]["committed"] == 3 and final["counts"]["pending_review"] == 0
    assert final["unique_sequences"]["committed"] == 2 and final["hash_mismatches"] == []
    with engine.connect() as c:
        versions = c.execute(select(func.count()).select_from(t.record_version)).scalar_one()
        statuses = {r.status for r in c.execute(select(t.file_task.c.status))}
    assert versions == 3
    assert statuses == {TaskStatus.COMPLETED.value}


def test_only_uploading_reviewers_can_migrate(m: Migration, engine: Engine) -> None:
    viewer = m.env.world.user("victor", {m.env.project: ["viewer"]})
    with pytest.raises(Forbidden):
        m.run(export(ROWS), actor=viewer)
    outsider = m.env.world.user("mallory", {})
    with pytest.raises(NotFound):
        m.run(export(ROWS), actor=outsider)
    with pytest.raises(InvalidRequest):
        m.run(b"not json")
    assert count(engine, t.legacy_batch) == 0


def test_legacy_records_are_immutable(m: Migration, engine: Engine) -> None:
    m.run(export(ROWS[:1]))
    with pytest.raises(DBAPIError, match="immutable"), engine.begin() as c:
        c.execute(text("UPDATE legacy_record SET legacy_id = 'L-99'"))


def test_the_command_line_tool(
    m: Migration, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in {
        "SEQUENCE_VAULT_ENV": "development",
        "SEQUENCE_VAULT_DATABASE_URL": database_url,
        "SEQUENCE_VAULT_STORAGE": "local",
        "SEQUENCE_VAULT_LOCAL_STORAGE_DIR": str(tmp_path / "objects"),
        "SEQUENCE_VAULT_SCANNER": "development",
    }.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "export.json"
    path.write_bytes(export(ROWS[:2]))
    args = [str(path), "--project", m.env.project, "--legacy-project", "Antibodies"]
    report = tmp_path / "report.json"
    spec = importlib.util.spec_from_file_location(
        "migrate", REPO_ROOT / "tools/legacy_migration/migrate.py"
    )
    assert spec and spec.loader
    migrate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migrate)

    assert migrate.main([*args, "--operator", "nobody@corp"]) == 2
    assert migrate.main([*args, "--operator", "operator@corp", "--report", str(report)]) == 0
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["counts"]["committed"] == 2
    assert PROTEIN_A not in report.read_text(encoding="utf-8")


def test_rows_over_the_residue_limit_are_rejected(m: Migration, engine: Engine) -> None:
    """Legacy rows obey the same 100,000-residue limit as uploads (B2)."""
    rows = [
        {"legacy_id": "L-1", "name": "Fits", "sequence": PROTEIN_A},
        {"legacy_id": "L-2", "name": "Huge", "sequence": "MKTAYIAKQR" * 20_000},
    ]
    report = m.run(export(rows))
    assert report["rejected"] == [{"index": 1, "legacy_id": "L-2", "reason": "sequence_limit"}]
    assert report["counts"]["committed"] == 1 and report["balanced"]
    assert count(engine, t.record_version) == 1
