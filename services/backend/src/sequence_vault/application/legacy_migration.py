"""Legacy system migration (design, "Legacy System Migration").

A legacy export is stored as a read-only snapshot, like any upload, and gets its own task and
run. Each legacy row becomes a ``legacy_import`` candidate whose sequence is typed text: the
originals are unavailable, so no evidence is fabricated. The same deterministic QC runs. Clean
rows are approved and committed by the operator through the ordinary commit transaction;
anything QC flags stays in the review queue. Nothing is cleaned up silently.

The reconciliation report compares the whole export with what the system holds now, so a
dry run, a first import and an incremental re-import before cutover all report the same way.
"""

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sequence_vault.application.authorization import Action, Actor, Role, authorize
from sequence_vault.application.commit import CommitItem, CommitService
from sequence_vault.application.errors import InvalidRequest
from sequence_vault.application.ports import (
    CandidateRow,
    FileRow,
    LegacyBatchRow,
    LegacyLink,
    ObjectStore,
    RunRow,
    Scanner,
    TaskRow,
    UnitOfWork,
    UnitOfWorkFactory,
)
from sequence_vault.application.review import (
    ReviewService,
    residue_count,
    settle_task,
    with_publication_issues,
)
from sequence_vault.domain.candidate import Candidate, CandidateStatus
from sequence_vault.domain.extraction import Name
from sequence_vault.domain.naming import name_key
from sequence_vault.domain.publication import sequence_sha256
from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    QcResult,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import QcRegistry, Severity
from sequence_vault.domain.task import FileTask, TaskStatus

Json = dict[str, Any]
PARSER_VERSION = "legacy-export-1"
PUBLISHED = {CandidateStatus.COMMITTED.value}
CLOSED = {
    CandidateStatus.REJECTED.value,
    CandidateStatus.ARCHIVED.value,
    CandidateStatus.SUPERSEDED.value,
}
MOLECULE_HINTS = {
    None: MoleculeType.PROTEIN,
    "protein": MoleculeType.PROTEIN,
    "dna": MoleculeType.NUCLEIC_ACID,
    "rna": MoleculeType.NUCLEIC_ACID,
    "nucleic_acid": MoleculeType.NUCLEIC_ACID,
}


# -- reading the export ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegacyRow:
    index: int
    legacy_id: str
    name: str | None
    sequence: str
    molecule_hint: MoleculeType
    created_at: datetime | None
    updated_at: datetime | None

    @property
    def sequence_sha256(self) -> str:
        """Hash of the exact exported text, used to detect changes between exports."""
        return hashlib.sha256(self.sequence.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Rejected:
    index: int
    legacy_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class LegacyExport:
    source_system: str
    exported_at: datetime | None
    legacy_project: str
    total: int
    rows: tuple[LegacyRow, ...]
    rejected: tuple[Rejected, ...]
    permissions: tuple[tuple[str, str], ...]
    """(subject, role) pairs exported for this project."""


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(value)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed


def read_export(data: bytes, legacy_project: str, *, max_residues: int) -> LegacyExport:
    """Read the rows of one legacy project. Rows that cannot be traced or read are rejected
    with a reason; everything else is kept as exported, for QC to judge."""
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidRequest("The export is not UTF-8 JSON.", code="invalid_export") from error
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise InvalidRequest("The export has no records list.", code="invalid_export")
    source_system = _text(document.get("source_system"))
    if source_system is None:
        raise InvalidRequest("The export does not name its source system.", code="invalid_export")
    try:
        exported_at = (
            None if document.get("exported_at") is None else _timestamp(document["exported_at"])
        )
    except ValueError as error:
        raise InvalidRequest("exported_at must be an ISO 8601 timestamp with a zone.") from error

    records = [
        (index, item)
        for index, item in enumerate(document["records"])
        if isinstance(item, dict) and item.get("project") == legacy_project
    ]
    id_counts = Counter(_text(item.get("legacy_id")) for _, item in records)
    rows: list[LegacyRow] = []
    rejected: list[Rejected] = []
    for index, item in records:
        legacy_id = _text(item.get("legacy_id"))
        sequence = item.get("sequence", "")
        hint = item.get("molecule_type")
        if legacy_id is None:
            rejected.append(Rejected(index, None, "missing_legacy_id"))
            continue
        if id_counts[legacy_id] > 1:
            rejected.append(Rejected(index, legacy_id, "duplicate_legacy_id"))
            continue
        if not isinstance(sequence, str) or not isinstance(item.get("name", ""), str | None):
            rejected.append(Rejected(index, legacy_id, "invalid_field"))
            continue
        if hint not in MOLECULE_HINTS:
            rejected.append(Rejected(index, legacy_id, "unknown_molecule_type"))
            continue
        if residue_count(sequence) > max_residues:
            rejected.append(Rejected(index, legacy_id, "sequence_limit"))
            continue
        try:
            created = None if item.get("created_at") is None else _timestamp(item["created_at"])
            updated = None if item.get("updated_at") is None else _timestamp(item["updated_at"])
        except ValueError:
            rejected.append(Rejected(index, legacy_id, "invalid_timestamp"))
            continue
        rows.append(
            LegacyRow(
                index,
                legacy_id,
                _text(item.get("name")),
                sequence,
                MOLECULE_HINTS[hint],
                created,
                updated,
            )
        )
    # Import in legacy order, so later versions of a name meet the earlier ones.
    rows.sort(key=lambda row: (row.created_at is None, row.created_at or datetime.min, row.index))

    permissions = tuple(
        sorted(
            {
                (str(p["subject"]), str(p["role"]))
                for p in document.get("permissions", [])
                if isinstance(p, dict)
                and p.get("project") == legacy_project
                and _text(p.get("subject"))
                and _text(p.get("role"))
            }
        )
    )
    return LegacyExport(
        source_system=source_system,
        exported_at=exported_at,
        legacy_project=legacy_project,
        total=len(records),
        rows=tuple(rows),
        rejected=tuple(rejected),
        permissions=permissions,
    )


# -- QC and classification --------------------------------------------------------------


def _context(row: LegacyRow) -> ExtractionContext:
    return ExtractionContext(
        name_count=1 if row.name else 0,
        association_status="unambiguous",
        observation_kinds=frozenset(),
        molecule_type_hint=row.molecule_hint,
        coverage_risk=False,
    )


def _name(row: LegacyRow) -> Name | None:
    return None if row.name is None else Name(row.name, "legacy_import", None)


def is_clean(candidate: Candidate) -> bool:
    """Commit without a person only when QC found nothing a reviewer has to decide."""
    qc = candidate.qc
    return (
        candidate.status is CandidateStatus.NEEDS_REVIEW
        and candidate.name is not None
        and qc is not None
        and not qc.blocked
        and not qc.rule_ids(Severity.REVIEW)
    )


def _review_rules(qc: QcResult) -> list[str]:
    return sorted(qc.rule_ids(Severity.BLOCK) | qc.rule_ids(Severity.REVIEW))


@dataclass(frozen=True, slots=True)
class _Batch:
    batch_id: str
    file_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class _Planned:
    """A row's predicted or actual state for the report."""

    row: LegacyRow
    state: str  # committed, pending_review, closed, would_commit, would_review
    normalized_sha256: str | None
    published_sha256: str | None = None
    candidate_id: str | None = None
    rules: tuple[str, ...] = ()
    unchanged: bool = False


class LegacyMigration:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        store: ObjectStore,
        scanner: Scanner,
        registry: QcRegistry,
        *,
        max_residues: int,
    ) -> None:
        self.uow_factory = uow_factory
        self.store = store
        self.scanner = scanner
        self.registry = registry
        self.max_residues = max_residues
        self.review = ReviewService(uow_factory, registry, max_residues=max_residues)
        self.commits = CommitService(uow_factory, registry, max_residues=max_residues)

    def run(
        self,
        operator: Actor,
        project_id: str,
        file_name: str,
        data: bytes,
        legacy_project: str,
        *,
        dry_run: bool,
    ) -> Json:
        export = read_export(data, legacy_project, max_residues=self.max_residues)
        with self.uow_factory() as uow:
            roles = uow.members.roles(operator.user_id, project_id)
            authorize(roles, Action.COMMIT)
            authorize(roles, Action.UPLOAD)
            previous = uow.legacy.latest(project_id, [row.legacy_id for row in export.rows])
        if dry_run:
            planned = self._predict(export, project_id, previous)
            return self._report(export, project_id, data, None, planned, dry_run=True)
        batch = self._start_batch(operator, project_id, file_name, data, export)
        planned = [self._import(operator, project_id, batch, row, previous) for row in export.rows]
        with self.uow_factory() as uow:
            latest = uow.legacy.latest(project_id, [row.legacy_id for row in export.rows])
            planned = [self._observe(item, latest) for item in planned]
            report = self._report(export, project_id, data, batch.batch_id, planned, dry_run=False)
            report["permissions"] = self._permissions(uow, project_id, export)
            uow.legacy.finish_batch(batch.batch_id, report)
            task = uow.tasks.get_by_file(batch.file_id, for_update=True)
            assert task is not None
            uow.tasks.save(replace(task, task=task.task.advance(TaskStatus.VALIDATING)))
            settle_task(uow, batch.file_id)
            uow.audit.record(
                operator.tenant_id,
                operator.user_id,
                "legacy.batch_finished",
                "legacy_batch",
                batch.batch_id,
                {"counts": report["counts"], "balanced": report["balanced"]},
            )
            uow.commit()
        return report

    # -- dry run ------------------------------------------------------------------------

    def _predict(
        self, export: LegacyExport, project_id: str, previous: dict[str, LegacyLink]
    ) -> list[_Planned]:
        """QC every row against the current project without writing anything. Rows earlier in
        the same export count as published, so in-export conflicts show up too."""
        planned: list[_Planned] = []
        batch_names: dict[str, str] = {}
        with self.uow_factory() as uow:
            for row in export.rows:
                link = previous.get(row.legacy_id)
                if link is not None and _unchanged(link, row):
                    planned.append(self._from_link(row, link))
                    continue
                candidate = self._candidate(uow, project_id, "dry_run", row)
                qc = candidate.qc
                assert qc is not None
                normalized = qc.normalized.sequence if qc.normalized else ""
                digest = sequence_sha256(normalized) if normalized else None
                rules = list(_review_rules(qc))
                key = name_key(row.name) if row.name else None
                if (
                    key is not None
                    and digest is not None
                    and batch_names.get(key, digest) != digest
                ):
                    rules.append("QC09")
                if is_clean(candidate) and not rules:
                    if key is not None and digest is not None:
                        batch_names[key] = digest
                    planned.append(_Planned(row, "would_commit", digest, digest))
                else:
                    planned.append(
                        _Planned(row, "would_review", digest, rules=tuple(sorted(rules)))
                    )
        return planned

    # -- import -------------------------------------------------------------------------

    def _start_batch(
        self, operator: Actor, project_id: str, file_name: str, data: bytes, export: LegacyExport
    ) -> _Batch:
        verdict = self.scanner.scan(data)
        if not verdict.clean:
            raise InvalidRequest("The export failed the malware scan.", code="infected")
        batch_id = f"legacy_{uuid.uuid4().hex}"
        file_id = f"file_{uuid.uuid4().hex}"
        run_id = f"run_{uuid.uuid4().hex}"
        object_key = f"sources/{operator.tenant_id}/{file_id}"
        digest = hashlib.sha256(data).hexdigest()
        self.store.put(object_key, data)
        with self.uow_factory() as uow:
            uow.files.create(
                FileRow(
                    file_id=file_id,
                    tenant_id=operator.tenant_id,
                    project_id=project_id,
                    uploaded_by=operator.user_id,
                    original_name=file_name,
                    declared_bytes=len(data),
                    declared_sha256=digest,
                    byte_count=None,
                    sha256=None,
                    object_key=object_key,
                    detected_type=None,
                    security_status="awaiting_upload",
                )
            )
            uow.files.mark_uploaded(file_id, len(data), digest)
            uow.files.set_security(file_id, "clean", "legacy_export")
            uow.runs.create(
                RunRow(
                    run_id=run_id,
                    file_id=file_id,
                    generation=1,
                    qc_version=self.registry.version,
                    schema_version="1.0",
                    parser_version=PARSER_VERSION,
                    model_version=None,
                    prompt_version=None,
                    coverage=None,
                    extraction_result=None,
                ),
                parse_options={"legacy_project": export.legacy_project},
                source_encoding="utf-8",
            )
            uow.tasks.create(
                TaskRow(
                    # Validating until every row is in, so a commit cannot complete it early.
                    task=FileTask(f"task_{uuid.uuid4().hex}", TaskStatus.VALIDATING),
                    file_id=file_id,
                    current_run_id=run_id,
                    generation=1,
                )
            )
            uow.legacy.create_batch(
                LegacyBatchRow(
                    batch_id=batch_id,
                    tenant_id=operator.tenant_id,
                    project_id=project_id,
                    file_id=file_id,
                    operator_id=operator.user_id,
                    source_system=export.source_system,
                    legacy_project=export.legacy_project,
                    exported_at=export.exported_at,
                )
            )
            uow.audit.record(
                operator.tenant_id,
                operator.user_id,
                "legacy.batch_started",
                "legacy_batch",
                batch_id,
                {"file_id": file_id, "sha256": digest, "rows": export.total},
            )
            uow.commit()
        return _Batch(batch_id, file_id, run_id)

    def _candidate(
        self, uow: UnitOfWork, project_id: str, run_id: str, row: LegacyRow
    ) -> Candidate:
        name = _name(row)
        qc = evaluate_typed(self.registry, row.sequence, _context(row))
        draft = Candidate.legacy(f"cand_{uuid.uuid4().hex}", run_id, name, row.sequence, qc)
        probe = CandidateRow(draft, "", project_id, "", None)
        qc = with_publication_issues(uow, self.registry, probe, name, qc)
        return Candidate.legacy(draft.candidate_id, run_id, name, row.sequence, qc)

    def _import(
        self,
        operator: Actor,
        project_id: str,
        batch: _Batch,
        row: LegacyRow,
        previous: dict[str, LegacyLink],
    ) -> _Planned:
        link = previous.get(row.legacy_id)
        if link is not None and _unchanged(link, row):
            return _Planned(row, "", None, candidate_id=link.candidate_id, unchanged=True)
        with self.uow_factory() as uow:
            # QC09/QC10 see everything committed so far, including earlier rows of this export.
            candidate = self._candidate(uow, project_id, batch.run_id, row)
            uow.candidates.add(
                CandidateRow(candidate, operator.tenant_id, project_id, batch.file_id, None)
            )
            uow.legacy.add(
                batch.batch_id,
                project_id,
                row.legacy_id,
                row.name or "",
                row.created_at,
                row.updated_at,
                row.sequence_sha256,
                candidate.candidate_id,
            )
            uow.audit.record(
                operator.tenant_id,
                operator.user_id,
                "candidate.legacy_imported",
                "candidate",
                candidate.candidate_id,
                {"batch_id": batch.batch_id, "legacy_id": row.legacy_id},
            )
            uow.commit()
        if is_clean(candidate):
            # A conflict (someone published the name meanwhile) leaves the candidate approved
            # but unpublished; the report lists it as pending review.
            self.review.decide(operator, candidate.candidate_id, candidate.revision, approve=True)
            self.commits.commit(
                operator,
                f"legacy:{batch.batch_id}",
                [CommitItem(candidate.candidate_id, candidate.revision)],
            )
        return _Planned(row, "", None, candidate_id=candidate.candidate_id)

    def _observe(self, item: _Planned, latest: dict[str, LegacyLink]) -> _Planned:
        link = latest[item.row.legacy_id]
        return replace(self._from_link(item.row, link), unchanged=item.unchanged)

    def _from_link(self, row: LegacyRow, link: LegacyLink) -> _Planned:
        with self.uow_factory() as uow:
            stored = uow.candidates.get(link.candidate_id)
        assert stored is not None
        qc = stored.candidate.qc
        normalized = qc.normalized.sequence if qc is not None and qc.normalized else ""
        state = (
            "committed"
            if link.candidate_status in PUBLISHED
            else "closed"
            if link.candidate_status in CLOSED
            else "pending_review"
        )
        return _Planned(
            row,
            state,
            sequence_sha256(normalized) if normalized else None,
            sequence_sha256(link.published_sequence) if link.published_sequence else None,
            link.candidate_id,
            tuple(_review_rules(qc)) if qc is not None and state == "pending_review" else (),
            unchanged=True,
        )

    # -- reconciliation -----------------------------------------------------------------

    def _permissions(self, uow: UnitOfWork, project_id: str, export: LegacyExport) -> Json:
        known = {role.value for role in Role}
        granted = uow.legacy.grants(project_id)
        legacy = set(export.permissions)
        unmapped = sorted(p for p in legacy if p[1] not in known)
        mapped = legacy - set(unmapped)
        return {
            "legacy": len(legacy),
            "matched": len(mapped & granted),
            "missing": [{"subject": s, "role": r} for s, r in sorted(mapped - granted)],
            "unmapped_roles": [{"subject": s, "role": r} for s, r in unmapped],
            "only_in_new_system": [{"subject": s, "role": r} for s, r in sorted(granted - legacy)],
        }

    def _report(
        self,
        export: LegacyExport,
        project_id: str,
        data: bytes,
        batch_id: str | None,
        planned: Sequence[_Planned],
        *,
        dry_run: bool,
    ) -> Json:
        states = Counter(item.state for item in planned)
        committed = [item for item in planned if item.state in ("committed", "would_commit")]
        pending = [item for item in planned if item.state in ("pending_review", "would_review")]
        accepted = len(export.rows)
        counts = {
            "legacy_records": export.total,
            "rejected": len(export.rejected),
            "accepted": accepted,
            "unchanged_since_last_import": sum(item.unchanged for item in planned),
            "committed": len(committed),
            "pending_review": len(pending),
            "closed_without_publishing": states["closed"],
        }
        mismatches = sorted(
            item.row.legacy_id
            for item in committed
            if item.published_sha256 is None or item.published_sha256 != item.normalized_sha256
        )
        report: Json = {
            "dry_run": dry_run,
            "batch_id": batch_id,
            "project_id": project_id,
            "source_system": export.source_system,
            "legacy_project": export.legacy_project,
            "exported_at": export.exported_at.isoformat() if export.exported_at else None,
            "export_sha256": hashlib.sha256(data).hexdigest(),
            "qc_version": self.registry.version,
            "counts": counts,
            "balanced": export.total == len(export.rejected) + accepted
            and accepted == counts["committed"] + counts["pending_review"] + states["closed"],
            "unique_sequences": {
                "accepted": len(
                    {item.normalized_sha256 for item in planned if item.normalized_sha256}
                ),
                "committed": len(
                    {item.published_sha256 for item in committed if item.published_sha256}
                ),
            },
            "hash_mismatches": mismatches,
            "rejected": [
                {"index": r.index, "legacy_id": r.legacy_id, "reason": r.reason}
                for r in export.rejected
            ],
            "pending_review": [
                {
                    "legacy_id": item.row.legacy_id,
                    "candidate_id": item.candidate_id,
                    "rules": list(item.rules),
                }
                for item in pending
            ],
        }
        if dry_run:
            known = {role.value for role in Role}
            report["permissions"] = {
                "legacy": len(export.permissions),
                "unmapped_roles": [
                    {"subject": s, "role": r} for s, r in export.permissions if r not in known
                ],
            }
        return report


def _unchanged(link: LegacyLink, row: LegacyRow) -> bool:
    return link.sequence_sha256 == row.sequence_sha256 and link.legacy_name == (row.name or "")
