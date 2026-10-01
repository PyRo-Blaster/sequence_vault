"""Read-side SQL for listing and detail screens. Authorization happens in the application."""

import base64
import json
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, and_, func, literal, or_, select, tuple_

from sequence_vault.adapters.persistence import tables as t

Json = dict[str, Any]


def encode_cursor(values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode()


def decode_cursor(cursor: str | None) -> list[Any] | None:
    if not cursor:
        return None
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (ValueError, json.JSONDecodeError):
        raise ValueError("Invalid cursor.") from None
    if not isinstance(values, list):
        raise ValueError("Invalid cursor.")
    return values


def _iso(value: Any) -> str | None:
    return None if value is None else value.isoformat()


class SqlReadModel:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def user_by_subject(self, subject: str) -> Json | None:
        with self.engine.connect() as c:
            row = c.execute(select(t.app_user).where(t.app_user.c.subject == subject)).first()
        if row is None:
            return None
        return {
            "user_id": row.id,
            "tenant_id": row.tenant_id,
            "display_name": row.display_name,
            "subject": row.subject,
        }

    def projects_for_user(self, user_id: str) -> list[Json]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(t.project.c.id, t.project.c.name, t.project_member.c.role)
                .join(t.project_member, t.project_member.c.project_id == t.project.c.id)
                .where(t.project_member.c.user_id == user_id)
                .order_by(t.project.c.name, t.project_member.c.role)
            ).all()
        projects: dict[str, Json] = {}
        for project_id, name, role in rows:
            projects.setdefault(project_id, {"project_id": project_id, "name": name, "roles": []})
            projects[project_id]["roles"].append(role)
        return list(projects.values())

    def _task_query(self) -> Any:
        f, k = t.source_file, t.file_task
        return select(
            k.c.id,
            k.c.status,
            k.c.failure_code,
            k.c.generation,
            k.c.current_run_id,
            k.c.created_at,
            k.c.updated_at,
            f.c.id.label("file_id"),
            f.c.project_id,
            f.c.tenant_id,
            f.c.original_name,
            f.c.byte_count,
            f.c.detected_type,
            f.c.security_status,
            f.c.uploaded_by,
        ).join(f, f.c.id == k.c.file_id)

    def _task_json(self, c: Any, row: Any) -> Json:
        counts: dict[str, int] = {}
        if row.current_run_id:
            for status, count in c.execute(
                select(t.candidate.c.status, func.count())
                .where(t.candidate.c.run_id == row.current_run_id)
                .group_by(t.candidate.c.status)
            ):
                counts[status] = count
        return {
            "task_id": row.id,
            "file_id": row.file_id,
            "project_id": row.project_id,
            "tenant_id": row.tenant_id,
            "file_name": row.original_name,
            "byte_count": row.byte_count,
            "detected_type": row.detected_type,
            "security_status": row.security_status,
            "status": row.status,
            "failure_code": row.failure_code,
            "generation": row.generation,
            "run_id": row.current_run_id,
            "candidate_counts": counts,
            "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at),
        }

    def task(self, task_id: str) -> Json | None:
        with self.engine.connect() as c:
            row = c.execute(self._task_query().where(t.file_task.c.id == task_id)).first()
            return None if row is None else self._task_json(c, row)

    def tasks(
        self, project_id: str, limit: int, cursor: list[Any] | None
    ) -> tuple[list[Json], str | None]:
        query = self._task_query().where(t.source_file.c.project_id == project_id)
        if cursor:
            query = query.where(
                tuple_(t.file_task.c.created_at, t.file_task.c.id)
                < tuple_(literal(datetime.fromisoformat(cursor[0])), literal(cursor[1]))
            )
        query = query.order_by(t.file_task.c.created_at.desc(), t.file_task.c.id.desc()).limit(
            limit + 1
        )
        with self.engine.connect() as c:
            rows = c.execute(query).all()
            items = [self._task_json(c, row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor([items[-1]["created_at"], items[-1]["task_id"]])
            if len(rows) > limit
            else None
        )
        return items, next_cursor

    def run(self, run_id: str) -> Json | None:
        with self.engine.connect() as c:
            row = c.execute(select(t.extraction_run).where(t.extraction_run.c.id == run_id)).first()
        if row is None:
            return None
        return {
            "run_id": row.id,
            "generation": row.generation,
            "parser_version": row.parser_version,
            "model_version": row.model_version,
            "prompt_version": row.prompt_version,
            "schema_version": row.schema_version,
            "qc_version": row.qc_version,
            "parse_options": row.parse_options,
            "source_encoding": row.source_encoding,
            "coverage": row.coverage,
        }

    def records(
        self,
        project_ids: list[str],
        *,
        q: str | None,
        sequence_sha256: str | None,
        min_length: int | None,
        max_length: int | None,
        limit: int,
        cursor: list[Any] | None,
    ) -> tuple[list[Json], str | None]:
        r, v, e, p = t.record, t.record_version, t.sequence_entity, t.project
        query = (
            select(
                r.c.id,
                r.c.name_key,
                r.c.display_name,
                r.c.project_id,
                p.c.name.label("project"),
                v.c.version_no,
                v.c.created_at,
                e.c.length,
                e.c.sha256,
            )
            .join(v, and_(v.c.record_id == r.c.id, v.c.is_current))
            .join(e, e.c.id == v.c.sequence_entity_id)
            .join(p, p.c.id == r.c.project_id)
            .where(r.c.project_id.in_(project_ids))
        )
        if q:
            pattern = (
                "%"
                + q.strip().casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            query = query.where(r.c.name_key.like(pattern, escape="\\"))
        if sequence_sha256:
            query = query.where(e.c.sha256 == sequence_sha256)
        if min_length is not None:
            query = query.where(e.c.length >= min_length)
        if max_length is not None:
            query = query.where(e.c.length <= max_length)
        if cursor:
            query = query.where(
                or_(r.c.name_key > cursor[0], and_(r.c.name_key == cursor[0], r.c.id > cursor[1]))
            )
        query = query.order_by(r.c.name_key, r.c.id).limit(limit + 1)
        with self.engine.connect() as c:
            rows = c.execute(query).all()
        items = [
            {
                "record_id": row.id,
                "name": row.display_name,
                "project_id": row.project_id,
                "project": row.project,
                "version_no": row.version_no,
                "length": row.length,
                "sha256": row.sha256,
                "updated_at": _iso(row.created_at),
            }
            for row in rows[:limit]
        ]
        next_cursor = (
            encode_cursor([rows[limit - 1].name_key, rows[limit - 1].id])
            if len(rows) > limit
            else None
        )
        return items, next_cursor

    def record(self, record_id: str) -> Json | None:
        r, v, e, u = t.record, t.record_version, t.sequence_entity, t.app_user
        pv = t.provenance
        with self.engine.connect() as c:
            head = c.execute(select(r).where(r.c.id == record_id)).first()
            if head is None:
                return None
            versions = c.execute(
                select(
                    v.c.id,
                    v.c.version_no,
                    v.c.is_current,
                    v.c.created_at,
                    v.c.previous_version_id,
                    e.c.canonical_sequence,
                    e.c.length,
                    e.c.sha256,
                    u.c.display_name.label("by"),
                )
                .join(e, e.c.id == v.c.sequence_entity_id)
                .join(u, u.c.id == v.c.created_by)
                .where(v.c.record_id == record_id)
                .order_by(v.c.version_no.desc())
            ).all()
            approver, committer = u.alias("approver"), u.alias("committer")
            provenance = c.execute(
                select(
                    pv.c.record_version_id,
                    pv.c.candidate_id,
                    pv.c.candidate_revision,
                    pv.c.run_id,
                    pv.c.file_id,
                    t.source_file.c.original_name,
                    pv.c.evidence,
                    pv.c.transformation_log,
                    pv.c.created_at,
                    approver.c.display_name.label("approved_by"),
                    committer.c.display_name.label("committed_by"),
                )
                .join(t.source_file, t.source_file.c.id == pv.c.file_id)
                .join(approver, approver.c.id == pv.c.approved_by)
                .join(committer, committer.c.id == pv.c.committed_by)
                .where(pv.c.record_version_id.in_([row.id for row in versions]))
                .order_by(pv.c.created_at)
            ).all()
        by_version: dict[str, list[Json]] = {}
        for row in provenance:
            by_version.setdefault(row.record_version_id, []).append(
                {
                    "candidate_id": row.candidate_id,
                    "candidate_revision": row.candidate_revision,
                    "run_id": row.run_id,
                    "file_id": row.file_id,
                    "file_name": row.original_name,
                    "evidence": row.evidence,
                    "transformation_log": row.transformation_log,
                    "approved_by": row.approved_by,
                    "committed_by": row.committed_by,
                    "committed_at": _iso(row.created_at),
                }
            )
        return {
            "record_id": head.id,
            "tenant_id": head.tenant_id,
            "project_id": head.project_id,
            "name": head.display_name,
            "created_at": _iso(head.created_at),
            "versions": [
                {
                    "version_id": row.id,
                    "version_no": row.version_no,
                    "is_current": row.is_current,
                    "previous_version_id": row.previous_version_id,
                    "sequence": row.canonical_sequence,
                    "length": row.length,
                    "sha256": row.sha256,
                    "created_by": row.by,
                    "created_at": _iso(row.created_at),
                    "provenance": by_version.get(row.id, []),
                }
                for row in versions
            ],
        }
