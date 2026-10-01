"""Deduplication and version decisions for committing one approved candidate (QC09, QC10)."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sequence_vault.domain.qc.registry import Issue, QcRegistry


def sequence_sha256(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredEntity:
    """A sequence entity found by (tenant, type, sha256); its content is compared in full."""

    entity_id: str
    sequence: str


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """The project's record with the candidate's name_key, and its current version."""

    record_id: str
    current_version_no: int
    current_sequence: str


class RecordAction(StrEnum):
    CREATE_RECORD = "create_record"
    ADD_PROVENANCE = "add_provenance"
    NEW_VERSION = "new_version"
    NEEDS_DECISION = "needs_decision"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    reuse_entity_id: str | None
    record_action: RecordAction
    issues: tuple[Issue, ...]


def plan_publication(
    registry: QcRegistry,
    sequence: str,
    hash_matches: Sequence[StoredEntity],
    record: StoredRecord | None,
    qc09_resolution: str | None,
) -> PublicationPlan:
    """Decide what committing ``sequence`` writes. Never overwrites a published version."""
    reuse = next((entity.entity_id for entity in hash_matches if entity.sequence == sequence), None)
    issues: list[Issue] = []
    if reuse is not None:
        issues.append(registry.issue("QC10", "An identical sequence is stored; it will be reused."))
    if record is None:
        action = RecordAction.CREATE_RECORD
    elif record.current_sequence == sequence:
        action = RecordAction.ADD_PROVENANCE
    else:
        issues.append(
            registry.issue(
                "QC09",
                f"This name already has version {record.current_version_no} "
                "with a different sequence.",
            )
        )
        action = {
            "create_new_version": RecordAction.NEW_VERSION,
            "cancel": RecordAction.CANCEL,
        }.get(qc09_resolution or "", RecordAction.NEEDS_DECISION)
    return PublicationPlan(reuse, action, tuple(issues))
