"""Provisioning: tenants, projects, users and project roles. Every change is audited."""

import uuid
from typing import Any

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.dialects.postgresql import insert

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.application.authorization import Role


def _audit(
    c: Connection,
    tenant_id: str,
    event: str,
    entity: str,
    entity_id: str,
    actor_id: str | None = None,
    **detail: str,
) -> None:
    c.execute(
        t.audit_event.insert().values(
            tenant_id=tenant_id,
            actor_id=actor_id,
            event=event,
            entity_type=entity,
            entity_id=entity_id,
            detail=detail,
        )
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


class SqlProjectAdmin:
    """Membership management and quality figures for one project. Every change is audited."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.provisioning = Provisioning(engine)

    def project_tenant(self, project_id: str) -> str | None:
        with self.engine.connect() as c:
            value = c.execute(
                select(t.project.c.tenant_id).where(t.project.c.id == project_id)
            ).scalar()
        return None if value is None else str(value)

    def members(self, project_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(
                    t.app_user.c.id,
                    t.app_user.c.subject,
                    t.app_user.c.display_name,
                    t.project_member.c.role,
                )
                .join(t.project_member, t.project_member.c.user_id == t.app_user.c.id)
                .where(t.project_member.c.project_id == project_id)
                .order_by(t.app_user.c.display_name, t.project_member.c.role)
            ).all()
        members: dict[str, dict[str, Any]] = {}
        for user_id, subject, name, role in rows:
            members.setdefault(
                user_id, {"user_id": user_id, "subject": subject, "display_name": name, "roles": []}
            )["roles"].append(role)
        return list(members.values())

    def user_in_tenant(self, tenant_id: str, subject: str) -> str | None:
        with self.engine.connect() as c:
            value = c.execute(
                select(t.app_user.c.id).where(
                    t.app_user.c.tenant_id == tenant_id, t.app_user.c.subject == subject
                )
            ).scalar()
        return None if value is None else str(value)

    def grant(self, actor_id: str, project_id: str, user_id: str, role: Role) -> None:
        self.provisioning.grant(project_id, user_id, role, actor_id=actor_id)

    def revoke(self, actor_id: str, project_id: str, user_id: str, role: Role) -> None:
        self.provisioning.revoke(project_id, user_id, role, actor_id=actor_id)

    def admin_count(self, project_id: str) -> int:
        with self.engine.connect() as c:
            return int(
                c.execute(
                    select(func.count())
                    .select_from(t.project_member)
                    .where(
                        t.project_member.c.project_id == project_id,
                        t.project_member.c.role == Role.PROJECT_ADMIN.value,
                    )
                ).scalar_one()
            )

    def quality(self, project_id: str) -> dict[str, Any]:
        f, k, cand, run = t.source_file, t.file_task, t.candidate, t.extraction_run
        with self.engine.connect() as c:
            tasks: dict[str, int] = dict(
                c.execute(
                    select(k.c.status, func.count())
                    .join(f, f.c.id == k.c.file_id)
                    .where(f.c.project_id == project_id)
                    .group_by(k.c.status)
                ).all()
            )
            failures: dict[str, int] = dict(
                c.execute(
                    select(k.c.failure_code, func.count())
                    .join(f, f.c.id == k.c.file_id)
                    .where(f.c.project_id == project_id, k.c.failure_code.is_not(None))
                    .group_by(k.c.failure_code)
                ).all()
            )
            formats = [
                {
                    "format": fmt or "unknown",
                    "tasks": total,
                    "failed": failed,
                    "failure_rate": _ratio(failed, total),
                }
                for fmt, total, failed in c.execute(
                    select(
                        f.c.detected_type,
                        func.count(),
                        func.count().filter(k.c.status.in_(["FAILED", "UNSUPPORTED"])),
                    )
                    .join(k, k.c.file_id == f.c.id)
                    .where(f.c.project_id == project_id)
                    .group_by(f.c.detected_type)
                    .order_by(f.c.detected_type)
                ).all()
            ]
            candidates: dict[str, int] = dict(
                c.execute(
                    select(cand.c.status, func.count())
                    .where(cand.c.project_id == project_id)
                    .group_by(cand.c.status)
                ).all()
            )
            reviewed = sum(candidates.get(s, 0) for s in ("APPROVED", "COMMITTED", "REJECTED"))
            manual = int(
                c.execute(
                    select(func.count())
                    .select_from(cand)
                    .where(
                        cand.c.project_id == project_id,
                        cand.c.body["origin"].astext == "manual_revision",
                    )
                ).scalar_one()
            )
            renamed = int(
                c.execute(
                    select(func.count(func.distinct(t.audit_event.c.entity_id)))
                    .join(cand, cand.c.id == t.audit_event.c.entity_id)
                    .where(
                        cand.c.project_id == project_id,
                        t.audit_event.c.event == "candidate.renamed",
                    )
                ).scalar_one()
            )
            commits: dict[str, int] = dict(
                c.execute(
                    select(t.commit_result.c.status, func.count())
                    .join(cand, cand.c.id == t.commit_result.c.candidate_id)
                    .where(cand.c.project_id == project_id)
                    .group_by(t.commit_result.c.status)
                ).all()
            )
            records = int(
                c.execute(
                    select(func.count())
                    .select_from(t.record)
                    .where(t.record.c.project_id == project_id)
                ).scalar_one()
            )
            runs = [
                {
                    "parser_version": parser,
                    "model_version": model,
                    "prompt_version": prompt,
                    "runs": count,
                }
                for parser, model, prompt, count in c.execute(
                    select(
                        run.c.parser_version,
                        run.c.model_version,
                        run.c.prompt_version,
                        func.count(),
                    )
                    .join(f, f.c.id == run.c.file_id)
                    .where(f.c.project_id == project_id)
                    .group_by(run.c.parser_version, run.c.model_version, run.c.prompt_version)
                    .order_by(run.c.parser_version)
                ).all()
            ]
        total_candidates = sum(v for s, v in candidates.items() if s != "SUPERSEDED")
        return {
            "tasks": tasks,
            "failure_codes": failures,
            "formats": formats,
            "candidates": candidates,
            "manual_revision_rate": _ratio(manual, reviewed),
            "rename_rate": _ratio(renamed, total_candidates),
            "commits": commits,
            "records": records,
            "runs": runs,
        }


class Provisioning:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def tenant(self, name: str) -> str:
        with self.engine.begin() as c:
            existing = c.execute(select(t.tenant.c.id).where(t.tenant.c.name == name)).scalar()
            if existing:
                return str(existing)
            tenant_id = f"tenant_{uuid.uuid4().hex[:12]}"
            c.execute(t.tenant.insert().values(id=tenant_id, name=name))
            _audit(c, tenant_id, "tenant.created", "tenant", tenant_id, name=name)
            return tenant_id

    def project(self, tenant_id: str, name: str) -> str:
        with self.engine.begin() as c:
            existing = c.execute(
                select(t.project.c.id).where(
                    t.project.c.tenant_id == tenant_id, t.project.c.name == name
                )
            ).scalar()
            if existing:
                return str(existing)
            project_id = f"proj_{uuid.uuid4().hex[:12]}"
            c.execute(t.project.insert().values(id=project_id, tenant_id=tenant_id, name=name))
            _audit(c, tenant_id, "project.created", "project", project_id, name=name)
            return project_id

    def user(self, tenant_id: str, subject: str, display_name: str) -> str:
        with self.engine.begin() as c:
            existing = c.execute(
                select(t.app_user.c.id).where(t.app_user.c.subject == subject)
            ).scalar()
            if existing:
                return str(existing)
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            c.execute(
                t.app_user.insert().values(
                    id=user_id, tenant_id=tenant_id, subject=subject, display_name=display_name
                )
            )
            _audit(c, tenant_id, "user.created", "user", user_id, subject=subject)
            return user_id

    def grant(
        self, project_id: str, user_id: str, role: Role, *, actor_id: str | None = None
    ) -> None:
        with self.engine.begin() as c:
            tenant_id: str = c.execute(
                select(t.project.c.tenant_id).where(t.project.c.id == project_id)
            ).scalar_one()
            c.execute(
                insert(t.project_member)
                .values(project_id=project_id, user_id=user_id, role=role.value)
                .on_conflict_do_nothing()
            )
            _audit(
                c,
                tenant_id,
                "member.granted",
                "project",
                project_id,
                actor_id,
                user_id=user_id,
                role=role.value,
            )

    def revoke(
        self, project_id: str, user_id: str, role: Role, *, actor_id: str | None = None
    ) -> None:
        with self.engine.begin() as c:
            tenant_id: str = c.execute(
                select(t.project.c.tenant_id).where(t.project.c.id == project_id)
            ).scalar_one()
            c.execute(
                t.project_member.delete().where(
                    t.project_member.c.project_id == project_id,
                    t.project_member.c.user_id == user_id,
                    t.project_member.c.role == role.value,
                )
            )
            _audit(
                c,
                tenant_id,
                "member.revoked",
                "project",
                project_id,
                actor_id,
                user_id=user_id,
                role=role.value,
            )
