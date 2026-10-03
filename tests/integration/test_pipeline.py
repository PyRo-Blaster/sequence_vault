"""P3 acceptance: upload to review-ready through the real worker and PostgreSQL."""

import hashlib
import io
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.adapters.security.clamd import EICAR
from sequence_vault.application.authorization import Actor
from sequence_vault.application.commit import CommitItem, CommitStatus
from sequence_vault.application.errors import Conflict, InvalidRequest, LimitExceeded
from sequence_vault.application.ports import Job, ScannerUnavailable, ScanVerdict
from sequence_vault.entrypoints.bootstrap import Container, build
from sequence_vault.settings import Settings
from sequence_vault.workers.worker import Worker
from tests.integration.world import World


class Env:
    def __init__(self, engine: Engine, tmp_path: Path) -> None:
        settings = Settings.from_env(
            {
                "SEQUENCE_VAULT_ENV": "development",
                "SEQUENCE_VAULT_STORAGE": "local",
                "SEQUENCE_VAULT_LOCAL_STORAGE_DIR": str(tmp_path / "objects"),
                "SEQUENCE_VAULT_SCANNER": "development",
            }
        )
        self.app: Container = build(settings, engine=engine)
        self.world = World(engine)
        self.project = self.world.project("Antibodies")
        self.alice = self.world.user("alice", {self.project: ["uploader", "reviewer"]})
        self.worker = Worker(self.app.queue, self.app.pipeline, worker_id="w1", delay=lambda _: 0)

    def upload(self, name: str, data: bytes, actor: Actor | None = None) -> str:
        actor = actor or self.alice
        digest = hashlib.sha256(data).hexdigest()
        row = self.app.uploads.create(actor, self.project, name, len(data), digest)
        self.app.uploads.put_content(actor, row.file_id, data)
        return self.app.uploads.complete(actor, row.file_id).task.task_id

    def task(self, task_id: str) -> tuple[str, str | None]:
        with self.app.uow() as uow:
            row = uow.tasks.get(task_id)
        assert row is not None
        return row.task.status.value, row.task.failure_code

    def candidates(self, task_id: str) -> list[dict[str, Any]]:
        with self.app.uow() as uow:
            task = uow.tasks.get(task_id)
            assert task is not None
            if task.current_run_id is None:
                return []
            rows = uow.candidates.list_for_run(task.current_run_id)
        return [
            {
                "id": r.candidate.candidate_id,
                "status": r.candidate.status.value,
                "name": None if r.candidate.name is None else r.candidate.name.value,
                "rules": sorted({i.rule_id for i in r.candidate.qc.issues})
                if r.candidate.qc
                else [],
                "completeness": r.candidate.completeness,
                "revision": r.candidate.revision,
            }
            for r in rows
        ]


@pytest.fixture
def env(engine: Engine, tmp_path: Path) -> Env:
    return Env(engine, tmp_path)


def test_t02_multi_record_fasta_reaches_review_and_commits(env: Env) -> None:
    task_id = env.upload("batch.fasta", b">A1 heavy\nMKTAYIAKQR\nQISFVKSHFS\n>A2\nMKTAYIAKQW\n")
    assert env.worker.run_until_idle() == 4
    assert env.task(task_id) == ("REVIEW_READY", None)
    found = env.candidates(task_id)
    assert [(c["name"], c["status"], c["completeness"]) for c in found] == [
        ("A1", "NEEDS_REVIEW", "complete"),
        ("A2", "NEEDS_REVIEW", "complete"),
    ]
    assert all(c["rules"] == ["QC02"] or c["rules"] == [] for c in found)
    for c in found:
        env.app.reviews.decide(env.alice, str(c["id"]), 1, approve=True)
    outcomes = env.app.commits.commit(env.alice, "k", [CommitItem(str(c["id"]), 1) for c in found])
    assert [o.status for o in outcomes] == [CommitStatus.COMMITTED] * 2
    assert env.task(task_id) == ("COMPLETED", None)
    with env.app.engine.connect() as connection:
        stored: list[str] = list(
            connection.execute(select(t.sequence_entity.c.canonical_sequence)).scalars()
        )
    assert sorted(stored) == ["MKTAYIAKQRQISFVKSHFS", "MKTAYIAKQW"]


def test_t01_filename_name_needs_confirmation(env: Env) -> None:
    task_id = env.upload("RSPO3_C07_v2.txt", b"MKTAYIAKQRQISFVKSHFSRQ\n")
    env.worker.run_until_idle()
    (candidate,) = env.candidates(task_id)
    assert (candidate["name"], candidate["rules"]) == ("RSPO3_C07_v2", ["QC07"])
    cid = str(candidate["id"])
    env.app.reviews.resolve(env.alice, cid, 1, "QC07", "select_name")
    env.app.reviews.decide(env.alice, cid, 1, approve=True)
    (outcome,) = env.app.commits.commit(env.alice, "k", [CommitItem(cid, 1)])
    assert outcome.status is CommitStatus.COMMITTED


def test_t09_name_without_sequence_waits_for_content(env: Env) -> None:
    task_id = env.upload("pending.fasta", b">A1\n>A2\nMKTAYIAKQR\n")
    env.worker.run_until_idle()
    first, second = env.candidates(task_id)
    assert (first["status"], second["status"]) == ("PENDING_CONTENT", "NEEDS_REVIEW")
    with env.app.engine.connect() as c:
        assert c.execute(select(t.sequence_entity)).first() is None


def test_named_entries_and_short_column_values_are_never_dropped(env: Env) -> None:
    """A name-only TXT entry waits for content; a short value in a sequence column is kept."""
    name_only = env.upload("Ab1.txt", b"Name: Ab1\n")
    short = env.upload("peptides.csv", b"name,sequence\nAb1,ACDE\n")
    env.worker.run_until_idle()
    (pending,) = env.candidates(name_only)
    assert (pending["status"], pending["name"]) == ("PENDING_CONTENT", "Ab1")
    (peptide,) = env.candidates(short)
    assert (peptide["status"], peptide["name"]) == ("NEEDS_REVIEW", "Ab1")


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("inner.fasta", ">A\nMKT\n")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("archive.fasta", _zip(), ("UNSUPPORTED", None)),
        (
            "legacy_office.fasta",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64,
            ("UNSUPPORTED", None),
        ),
        ("virus.fasta", b">A\n" + EICAR, ("FAILED", "infected")),
        ("binary.txt", bytes(range(256)) * 8, ("UNSUPPORTED", None)),
    ],
)
def test_t15_misleading_or_hostile_files_are_stopped(
    env: Env, name: str, data: bytes, expected: tuple[str, str | None]
) -> None:
    task_id = env.upload(name, data)
    env.worker.run_until_idle()
    assert env.task(task_id) == expected
    assert env.candidates(task_id) == []


def test_t15_declarations_are_enforced_before_processing(env: Env) -> None:
    data = b">A\nMKT\n"
    with pytest.raises(InvalidRequest, match="not accepted"):
        env.app.uploads.create(env.alice, env.project, "old.doc", len(data), "a" * 64)
    with pytest.raises(LimitExceeded):
        env.app.uploads.create(env.alice, env.project, "big.fasta", 30_000_000, "a" * 64)
    row = env.app.uploads.create(env.alice, env.project, "a.fasta", len(data), "b" * 64)
    with pytest.raises(InvalidRequest, match="do not match"):
        env.app.uploads.put_content(env.alice, row.file_id, data)
    with pytest.raises(Conflict, match="content first"):
        env.app.uploads.complete(env.alice, row.file_id)


def test_completion_is_idempotent(env: Env) -> None:
    data = b">A\nMKTAYIAKQR\n"
    row = env.app.uploads.create(
        env.alice, env.project, "a.fasta", len(data), hashlib.sha256(data).hexdigest()
    )
    env.app.uploads.put_content(env.alice, row.file_id, data)
    first = env.app.uploads.complete(env.alice, row.file_id)
    second = env.app.uploads.complete(env.alice, row.file_id)
    assert first.task.task_id == second.task.task_id
    assert env.app.queue.pending() == 1


def test_t20_cancelled_tasks_never_advance(env: Env) -> None:
    before = env.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    env.app.tasks.cancel(env.alice, before)
    env.worker.run_until_idle()
    assert env.task(before) == ("CANCELLED", None)
    midway = env.upload("b.fasta", b">B\nMKTAYIAKQR\n")
    env.worker.run_once()  # scanning finished, parsing queued
    env.app.tasks.cancel(env.alice, midway)
    env.worker.run_until_idle()
    assert env.task(midway) == ("CANCELLED", None)
    assert env.candidates(midway) == []


def test_duplicate_delivery_of_a_finished_stage_is_a_no_op(env: Env) -> None:
    task_id = env.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    env.worker.run_until_idle()
    env.app.pipeline.handle(Job(0, task_id, 1, "VALIDATING", 1))
    env.app.pipeline.handle(Job(0, task_id, 1, "PARSING", 1))
    assert len(env.candidates(task_id)) == 1


def test_expired_leases_are_reclaimed_and_live_ones_are_not(env: Env) -> None:
    env.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    env.upload("b.fasta", b">B\nMKTAYIAKQR\n")
    first = env.app.queue.claim("w1", 0.5)
    second = env.app.queue.claim("w2", 30)
    assert first and second and first.job_id != second.job_id
    assert env.app.queue.claim("w3", 30) is None
    time.sleep(0.7)
    taken_over = env.app.queue.claim("w3", 30)
    assert taken_over is not None
    assert (taken_over.job_id, taken_over.attempts) == (first.job_id, 2)
    assert not env.app.queue.heartbeat(first, "w1", 30)


class FlakyScanner:
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def scan(self, data: bytes) -> ScanVerdict:
        if self.failures > 0:
            self.failures -= 1
            raise ScannerUnavailable("clamd unreachable")
        return ScanVerdict(clean=True)


def test_transient_scanner_failures_retry_then_fail_closed(env: Env) -> None:
    env.app.pipeline.scanner = FlakyScanner(failures=2)
    recovered = env.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    env.worker.run_until_idle()
    assert env.task(recovered) == ("REVIEW_READY", None)

    env.app.pipeline.scanner = FlakyScanner(failures=100)
    down = env.upload("b.fasta", b">B\nMKTAYIAKQR\n")
    env.worker.run_until_idle()
    assert env.task(down) == ("FAILED", "scan_unavailable")
    with env.app.engine.connect() as c:
        statuses: dict[str, str] = dict(
            c.execute(select(t.source_file.c.original_name, t.source_file.c.security_status)).all()
        )
    assert statuses["b.fasta"] == "scan_failed"


def test_t16_reprocessing_supersedes_old_candidates_and_approvals(env: Env) -> None:
    task_id = env.upload("a.fasta", b">A\nMKTAYIAKQR\n")
    env.worker.run_until_idle()
    (old,) = env.candidates(task_id)
    env.app.reviews.decide(env.alice, str(old["id"]), 1, approve=True)
    env.app.tasks.reprocess(env.alice, task_id)
    env.worker.run_until_idle()
    (new,) = env.candidates(task_id)
    assert new["id"] != old["id"] and new["status"] == "NEEDS_REVIEW"
    (outcome,) = env.app.commits.commit(env.alice, "k", [CommitItem(str(old["id"]), 1)])
    assert outcome.status is CommitStatus.CONFLICT
    with env.app.uow() as uow:
        stale = uow.candidates.get(str(old["id"]))
    assert stale is not None and stale.candidate.status.value == "SUPERSEDED"
