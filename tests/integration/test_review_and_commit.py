"""P2 acceptance: review and commit against a real PostgreSQL (T10-T13, T18, T20)."""

from typing import Any

import pytest
from sqlalchemy import Engine, select

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.adapters.persistence.repositories import (
    SqlPublication,
    SqlUnitOfWork,
)
from sequence_vault.application.authorization import Actor
from sequence_vault.application.commit import CommitItem, CommitService, CommitStatus
from sequence_vault.application.errors import Conflict, Forbidden, InvalidRequest, NotFound
from sequence_vault.application.review import ReviewService
from sequence_vault.domain.publication import StoredRecord
from tests.integration.world import World


@pytest.fixture
def world(engine: Engine) -> World:
    return World(engine)


MAX_RESIDUES = 100_000


class Setup:
    def __init__(self, world: World) -> None:
        self.world = world
        self.project = world.project("Antibodies")
        self.alice = world.user("alice", {self.project: ["uploader", "reviewer"]})
        self.bob = world.user("bob", {self.project: ["uploader"]})
        self.review = ReviewService(world.uow, world.registry, max_residues=MAX_RESIDUES)
        self.commits = CommitService(world.uow, world.registry, max_residues=MAX_RESIDUES)

    def approved(
        self, records: list[tuple[str, str]], project: str | None = None, actor: Actor | None = None
    ) -> tuple[str, list[str]]:
        actor = actor or self.alice
        file_id, ids = self.world.fasta(project or self.project, actor, records)
        for candidate_id in ids:
            self.review.decide(actor, candidate_id, 1, approve=True)
        return file_id, ids

    def commit(
        self, candidate_id: str, revision: int = 1, key: str = "k1", actor: Actor | None = None
    ) -> Any:
        (outcome,) = self.commits.commit(
            actor or self.alice, key, [CommitItem(candidate_id, revision)]
        )
        return outcome


@pytest.fixture
def s(world: World) -> Setup:
    return Setup(world)


def test_approved_candidate_commits_and_completes_the_task(s: Setup) -> None:
    _, (cid,) = s.approved([("RSPO3_C07", "MKTAYIAKQR")])
    outcome = s.commit(cid)
    assert outcome.status is CommitStatus.COMMITTED
    with s.world.engine.connect() as c:
        version = c.execute(select(t.record_version)).one()
        task_status: str = c.execute(select(t.file_task.c.status)).scalar_one()
        events: list[str] = list(
            c.execute(select(t.audit_event.c.event).order_by(t.audit_event.c.id)).scalars()
        )
    assert (version.version_no, version.is_current, version.id) == (
        1,
        True,
        outcome.record_version_id,
    )
    assert task_status == "COMPLETED"
    assert events == ["candidate.approved", "candidate.committed"]
    assert s.world.count("provenance") == 1


def test_t11_retries_with_the_same_key_return_the_same_result(s: Setup) -> None:
    _, (cid,) = s.approved([("A1", "MKTAYIAKQR")])
    first, second = s.commit(cid, key="key-1"), s.commit(cid, key="key-1")
    assert first == second
    assert s.commit(cid, key="key-2").status is CommitStatus.ALREADY_COMMITTED
    assert s.world.count("record_version") == 1
    assert s.commit(cid, revision=2, key="key-1").reason == "idempotency_key_reused"


def test_a_replayed_key_is_authorized_again(s: Setup) -> None:
    """A cached result is returned only to someone who may commit the candidate now."""
    _, (cid,) = s.approved([("A1", "MKTAYIAKQR")])
    assert s.commit(cid, key="known-key").status is CommitStatus.COMMITTED
    viewer = s.world.user("victor", {s.project: ["viewer"]})
    outsider = s.world.user("olga", {s.world.project("Enzymes"): ["reviewer"]})
    for actor, reason in ((viewer, "forbidden"), (outsider, "not_found"), (s.bob, "forbidden")):
        replay = s.commit(cid, key="known-key", actor=actor)
        assert (replay.status, replay.reason) == (CommitStatus.FAILED, reason)
        assert replay.record_id is None and replay.record_version_id is None
    s.world.revoke(s.alice, s.project)
    assert s.commit(cid, key="known-key").reason == "not_found"


def test_t12_concurrent_edits_conflict_and_edits_void_approval(s: Setup) -> None:
    _, (cid,) = s.world.fasta(s.project, s.alice, [("A1", "MKTAYIAKQR")])
    s.review.rename(s.alice, cid, 1, "A1 heavy")
    with pytest.raises(Conflict) as stale:
        s.review.rename(s.bob, cid, 1, "A1 light")
    assert stale.value.code == "revision_conflict"
    s.review.decide(s.alice, cid, 2, approve=True)
    s.review.rename(s.bob, cid, 2, "A1 final")
    assert s.commit(cid, revision=2).reason == "stale_revision"


def test_uploaders_cannot_approve_and_outsiders_cannot_see(s: Setup) -> None:
    _, (cid,) = s.world.fasta(s.project, s.alice, [("A1", "MKTAYIAKQR")])
    with pytest.raises(Forbidden):
        s.review.decide(s.bob, cid, 1, approve=True)
    outsider = s.world.user("eve", {})
    with pytest.raises(NotFound):
        s.review.rename(outsider, cid, 1, "x")


def test_t13_permission_revoked_before_commit_fails(s: Setup) -> None:
    _, (first, second) = s.approved([("A1", "MKTAYIAKQR"), ("A2", "MKTAYIAKQW")])
    s.world.revoke(s.alice, s.project, "reviewer")
    assert s.commit(first).reason == "forbidden"
    s.world.revoke(s.alice, s.project)
    assert s.commit(second).reason == "not_found"
    assert s.world.count("record") == 0


def test_t10_same_name_new_sequence_needs_an_explicit_version(s: Setup) -> None:
    _, (v1,) = s.approved([("ABC", "MKTAYIAKQR")])
    assert s.commit(v1).status is CommitStatus.COMMITTED
    _, (v2,) = s.world.fasta(s.project, s.alice, [("abc ", "MKTAYIAKQW")])
    with pytest.raises(Conflict, match="QC09"):
        s.review.decide(s.alice, v2, 1, approve=True)
    with pytest.raises(InvalidRequest):
        s.review.resolve(s.alice, v2, 1, "QC09", "overwrite")
    s.review.resolve(s.alice, v2, 1, "QC09", "create_new_version")
    s.review.decide(s.alice, v2, 1, approve=True)
    outcome = s.commit(v2, key="k2")
    assert outcome.status is CommitStatus.COMMITTED
    with s.world.engine.connect() as c:
        versions = c.execute(
            select(t.record_version.c.version_no, t.record_version.c.is_current).order_by(
                t.record_version.c.version_no
            )
        ).all()
    assert [tuple(v) for v in versions] == [(1, False), (2, True)]


def test_t10_same_sequence_different_names_share_one_entity(s: Setup) -> None:
    _, ids = s.approved([("ABC", "MKTAYIAKQR"), ("XYZ", "MKTAYIAKQR")])
    assert [s.commit(cid).status for cid in ids] == [CommitStatus.COMMITTED] * 2
    assert (s.world.count("record"), s.world.count("sequence_entity")) == (2, 1)


def test_same_name_and_sequence_only_adds_provenance(s: Setup) -> None:
    _, (first,) = s.approved([("ABC", "MKTAYIAKQR")])
    s.commit(first)
    _, (second,) = s.approved([("ABC", "MKTAYIAKQR")])
    assert s.commit(second, key="k2").status is CommitStatus.COMMITTED
    assert (s.world.count("record_version"), s.world.count("provenance")) == (1, 2)


def test_t18_cross_project_reuse_stays_invisible(s: Setup) -> None:
    _, (in_a,) = s.approved([("ABC", "MKTAYIAKQR")])
    s.commit(in_a)
    project_b = s.world.project("Enzymes")
    carol = s.world.user("carol", {project_b: ["reviewer"]})
    _, (in_b,) = s.world.fasta(project_b, carol, [("Other", "MKTAYIAKQR")])
    with s.world.uow() as uow:
        row = uow.candidates.get(in_b)
    assert row is not None and row.candidate.qc is not None
    assert "QC10" not in {issue.rule_id for issue in row.candidate.qc.issues}
    s.review.decide(carol, in_b, 1, approve=True)
    assert s.commit(in_b, actor=carol).status is CommitStatus.COMMITTED
    assert s.world.count("sequence_entity") == 1


def test_t20_cancelled_task_and_unclean_file_cannot_commit(s: Setup) -> None:
    cancelled_file, (first,) = s.approved([("A1", "MKTAYIAKQR")])
    s.world.set_task_status(cancelled_file, "CANCELLED")
    assert s.commit(first).reason == "task_cancelled"
    infected_file, (second,) = s.approved([("A2", "MKTAYIAKQW")])
    s.world.set_file_status(infected_file, "infected")
    assert s.commit(second).reason == "file_not_clean"
    assert s.world.count("record") == 0


def test_a_lost_race_on_record_creation_retries_and_attaches(
    s: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate another transaction creating the record between our read and our insert."""
    _, (cid,) = s.approved([("RACE", "MKTAYIAKQR")])
    _, (rival,) = s.approved([("RACE", "MKTAYIAKQR")])
    assert s.commit(rival, key="rival").status is CommitStatus.COMMITTED

    calls = {"find": 0, "create": 0}
    original_find = SqlPublication.find_record
    original_create = SqlPublication.create_record

    def stale_find(
        self: SqlPublication, project_id: str, name_key: str, *, for_update: bool = False
    ) -> StoredRecord | None:
        calls["find"] += 1
        if calls["find"] == 1:
            return None
        return original_find(self, project_id, name_key, for_update=for_update)

    def counting_create(
        self: SqlPublication, tenant_id: str, project_id: str, name_key: str, display: str
    ) -> str:
        calls["create"] += 1
        return original_create(self, tenant_id, project_id, name_key, display)

    monkeypatch.setattr(SqlPublication, "find_record", stale_find)
    monkeypatch.setattr(SqlPublication, "create_record", counting_create)
    outcome = s.commit(cid, key="mine")
    assert calls["create"] == 1  # the stale attempt hit the unique constraint, then retried
    assert outcome.status is CommitStatus.COMMITTED
    assert (s.world.count("record"), s.world.count("record_version")) == (1, 1)
    assert s.world.count("provenance") == 2


def test_rejected_and_archived_candidates_settle_the_task(s: Setup, engine: Engine) -> None:
    _, (cid,) = s.world.fasta(s.project, s.alice, [("A1", "MKTAYIAKQR")])
    s.review.decide(s.alice, cid, 1, approve=False)
    with engine.connect() as c:
        assert c.execute(select(t.file_task.c.status)).scalar_one() == "COMPLETED"
    with SqlUnitOfWork(engine) as uow:
        row = uow.candidates.get(cid)
    assert row is not None and row.candidate.status.value == "REJECTED"


def test_the_residue_limit_holds_for_edits_and_commits(s: Setup) -> None:
    """Typed sequences cannot exceed the limit, and nothing over it is ever published (B2)."""
    _, (cid,) = s.approved([("Long", "MKTAYIAKQR")])
    with pytest.raises(InvalidRequest) as error:
        s.review.revise_sequence(
            s.alice, cid, 1, reason="typed", typed_sequence="MKTAYIAKQR" * 10_001
        )
    assert error.value.code == "sequence_limit"
    tighter = CommitService(s.world.uow, s.world.registry, max_residues=9)
    (outcome,) = tighter.commit(s.alice, "k1", [CommitItem(cid, 1)])
    assert (outcome.status, outcome.reason) == (CommitStatus.FAILED, "sequence_limit")
    assert s.world.count("record_version") == 0
