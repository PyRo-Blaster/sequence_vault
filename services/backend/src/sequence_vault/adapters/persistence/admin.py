"""Provisioning: tenants, projects, users and project roles. Every change is audited."""

import uuid

from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert

from sequence_vault.adapters.persistence import tables as t
from sequence_vault.application.authorization import Role


def _audit(
    c: Connection, tenant_id: str, event: str, entity: str, entity_id: str, **detail: str
) -> None:
    c.execute(
        t.audit_event.insert().values(
            tenant_id=tenant_id,
            actor_id=None,
            event=event,
            entity_type=entity,
            entity_id=entity_id,
            detail=detail,
        )
    )


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

    def grant(self, project_id: str, user_id: str, role: Role) -> None:
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
                user_id=user_id,
                role=role.value,
            )

    def revoke(self, project_id: str, user_id: str, role: Role) -> None:
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
                user_id=user_id,
                role=role.value,
            )
