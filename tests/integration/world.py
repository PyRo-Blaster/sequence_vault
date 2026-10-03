"""Seed realistic review-ready data for integration tests."""

import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy import Engine, delete, insert, update

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.adapters.persistence.repositories import SqlUnitOfWorkFactory
from sequence_vault.application.authorization import Actor
from sequence_vault.application.contract_mapping import context_for, records_from_extraction
from sequence_vault.application.ports import CandidateRow
from sequence_vault.application.review import with_publication_issues
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.qc.engine import evaluate_spans
from sequence_vault.domain.qc.registry import QcRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_registry() -> QcRegistry:
    data = json.loads((REPO_ROOT / "config/qc-rules.v1.json").read_text(encoding="utf-8"))
    return QcRegistry.from_dict(data)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class World:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.registry = load_registry()
        self.uow = SqlUnitOfWorkFactory(engine)
        self.tenant_id = _id("t")
        with engine.begin() as c:
            c.execute(insert(t.tenant).values(id=self.tenant_id, name="Dept"))

    def project(self, name: str) -> str:
        project_id = _id("p")
        with self.engine.begin() as c:
            c.execute(insert(t.project).values(id=project_id, tenant_id=self.tenant_id, name=name))
        return project_id

    def user(self, name: str, roles: dict[str, list[str]]) -> Actor:
        user_id = _id("u")
        with self.engine.begin() as c:
            c.execute(
                insert(t.app_user).values(
                    id=user_id, tenant_id=self.tenant_id, subject=f"{name}@corp", display_name=name
                )
            )
            for project_id, project_roles in roles.items():
                for role in project_roles:
                    c.execute(
                        insert(t.project_member).values(
                            project_id=project_id, user_id=user_id, role=role
                        )
                    )
        return Actor(user_id, self.tenant_id)

    def revoke(self, actor: Actor, project_id: str, role: str | None = None) -> None:
        query = delete(t.project_member).where(
            t.project_member.c.user_id == actor.user_id, t.project_member.c.project_id == project_id
        )
        if role:
            query = query.where(t.project_member.c.role == role)
        with self.engine.begin() as c:
            c.execute(query)

    def set_file_status(self, file_id: str, status: str) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(t.source_file)
                .where(t.source_file.c.id == file_id)
                .values(security_status=status)
            )

    def set_task_status(self, file_id: str, status: str) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(t.file_task).where(t.file_task.c.file_id == file_id).values(status=status)
            )

    def fasta(
        self, project_id: str, uploader: Actor, records: list[tuple[str, str]]
    ) -> tuple[str, list[str]]:
        """A clean, review-ready FASTA file. Returns (file_id, candidate_ids)."""
        file_id, run_id, task_id = _id("f"), _id("run"), _id("task")
        blocks, extracted = [], []
        text = "".join(f">{name}\n{sequence}\n" for name, sequence in records).encode()
        for index, (name, sequence) in enumerate(records):
            line = index * 2 + 1
            blocks.append((f"h{index}", "fasta_header", name, line))
            blocks.append((f"s{index}", "sequence", sequence, line + 1))
            extracted.append(
                {
                    "names": [
                        {
                            "value": name,
                            "source": "fasta_header",
                            "evidence": {"block_id": f"h{index}", "start": 0, "end": len(name)},
                        }
                    ],
                    "molecule_type": "protein",
                    "sequence_spans": [
                        {"block_id": f"s{index}", "start": 0, "end": len(sequence), "order": 1}
                    ],
                    "association_status": "unambiguous",
                    "observations": [],
                }
            )
        result = {
            "schema_version": "1.0",
            "file_id": file_id,
            "run_id": run_id,
            "records": extracted,
            "coverage": {"unresolved_blocks": [], "truncated": False},
        }
        document = {
            "blocks": [
                {"block_id": b, "type": kind, "raw_text": raw, "extraction_method": "text_parser"}
                for b, kind, raw, _ in blocks
            ],
            "coverage": result["coverage"],
        }
        with self.engine.begin() as c:
            c.execute(
                insert(t.source_file).values(
                    id=file_id,
                    tenant_id=self.tenant_id,
                    project_id=project_id,
                    uploaded_by=uploader.user_id,
                    original_name="batch.fasta",
                    declared_bytes=len(text),
                    declared_sha256=hashlib.sha256(text).hexdigest(),
                    byte_count=len(text),
                    sha256=hashlib.sha256(text).hexdigest(),
                    object_key=_id("obj"),
                    detected_type="fasta",
                    security_status="clean",
                )
            )
            c.execute(
                insert(t.file_task).values(id=task_id, file_id=file_id, status="REVIEW_READY")
            )
            c.execute(
                insert(t.extraction_run).values(
                    id=run_id,
                    file_id=file_id,
                    generation=1,
                    parser_version="fasta-1",
                    schema_version="1.0",
                    qc_version=self.registry.version,
                    parse_options={"tracked_changes_view": "not_applicable"},
                    source_encoding="utf-8",
                    coverage=result["coverage"],
                    extraction_result=result,
                )
            )
            for position, (block_id, kind, raw, line) in enumerate(blocks):
                c.execute(
                    insert(t.document_block).values(
                        run_id=run_id,
                        block_id=block_id,
                        position=position,
                        type=kind,
                        raw_text=raw,
                        location={"kind": "text", "line_start": line, "line_end": line},
                        extraction_method="text_parser",
                    )
                )
            c.execute(
                update(t.file_task).where(t.file_task.c.id == task_id).values(current_run_id=run_id)
            )
        candidate_ids = []
        block_text = {b: raw for b, _, raw, _ in blocks}
        with self.uow() as uow:
            for index, record in enumerate(records_from_extraction(result)):
                qc = evaluate_spans(
                    self.registry, block_text, record.spans, context_for(record, document)
                )
                candidate = Candidate.extracted(_id("c"), run_id, record.names, record.spans)
                row = CandidateRow(candidate, self.tenant_id, project_id, file_id, index)
                qc = with_publication_issues(uow, self.registry, row, candidate.name, qc)
                validated = candidate.validated(qc, parser_delimited=True)
                uow.candidates.add(
                    CandidateRow(validated, self.tenant_id, project_id, file_id, index)
                )
                candidate_ids.append(validated.candidate_id)
            uow.commit()
        return file_id, candidate_ids

    def count(self, table: str) -> int:
        from sqlalchemy import text

        with self.engine.connect() as c:
            return int(c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
