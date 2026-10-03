from sequence_vault.domain.publication import (
    RecordAction,
    StoredEntity,
    StoredRecord,
    plan_publication,
    sequence_sha256,
)
from sequence_vault.domain.qc.registry import QcRegistry


def test_new_name_and_new_sequence_create_a_record(registry: QcRegistry) -> None:
    plan = plan_publication(registry, "MKTAY", [], None, None)
    assert (plan.reuse_entity_id, plan.record_action, plan.issues) == (
        None,
        RecordAction.CREATE_RECORD,
        (),
    )


def test_reuses_an_entity_only_after_full_content_comparison(registry: QcRegistry) -> None:
    collision = StoredEntity("e-old", "DIFFERENT")
    identical = StoredEntity("e-same", "MKTAY")
    plan = plan_publication(registry, "MKTAY", [collision, identical], None, None)
    assert plan.reuse_entity_id == "e-same"
    assert [issue.rule_id for issue in plan.issues] == ["QC10"]


def test_same_name_same_sequence_only_adds_provenance(registry: QcRegistry) -> None:
    record = StoredRecord("r1", 1, "MKTAY")
    assert plan_publication(registry, "MKTAY", [], record, None).record_action is (
        RecordAction.ADD_PROVENANCE
    )


def test_same_name_new_sequence_needs_an_explicit_decision(registry: QcRegistry) -> None:
    record = StoredRecord("r1", 3, "MKTAY")
    undecided = plan_publication(registry, "MKTAW", [], record, None)
    assert undecided.record_action is RecordAction.NEEDS_DECISION
    assert [issue.rule_id for issue in undecided.issues] == ["QC09"]
    decided = plan_publication(registry, "MKTAW", [], record, "create_new_version")
    assert decided.record_action is RecordAction.NEW_VERSION


def test_sequence_hash_is_stable() -> None:
    assert sequence_sha256("ACDEFGHIKLMNPQRSTVWY") == (
        "5a52efc76a4a4ceb3c992ff17426b3545634646080bb6acec132c47c278c9846"
    )
