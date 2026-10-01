"""Project administration: members and roles, and the quality summary (design section 2)."""

from typing import Any, Protocol

from sequence_vault.application.authorization import Action, Actor, Role, authorize
from sequence_vault.application.errors import Conflict, InvalidRequest, NotFound
from sequence_vault.application.ports import UnitOfWorkFactory

Json = dict[str, Any]


class ProjectAdmin(Protocol):
    def project_tenant(self, project_id: str) -> str | None: ...
    def members(self, project_id: str) -> list[Json]: ...
    def user_in_tenant(self, tenant_id: str, subject: str) -> str | None: ...
    def grant(self, actor_id: str, project_id: str, user_id: str, role: Role) -> None: ...
    def revoke(self, actor_id: str, project_id: str, user_id: str, role: Role) -> None: ...
    def admin_count(self, project_id: str) -> int: ...
    def quality(self, project_id: str) -> Json: ...


class AdministrationService:
    def __init__(self, uow_factory: UnitOfWorkFactory, admin: ProjectAdmin) -> None:
        self.uow_factory = uow_factory
        self.admin = admin

    def _authorize(self, actor: Actor, project_id: str, action: Action) -> None:
        if self.admin.project_tenant(project_id) != actor.tenant_id:
            raise NotFound("Project not found.")
        with self.uow_factory() as uow:
            authorize(uow.members.roles(actor.user_id, project_id), action)

    def members(self, actor: Actor, project_id: str) -> list[Json]:
        self._authorize(actor, project_id, Action.MANAGE_MEMBERS)
        return self.admin.members(project_id)

    def grant(self, actor: Actor, project_id: str, subject: str, role: str) -> list[Json]:
        self._authorize(actor, project_id, Action.MANAGE_MEMBERS)
        user_id = self.admin.user_in_tenant(actor.tenant_id, subject.strip())
        if user_id is None:
            raise InvalidRequest("No provisioned user has that sign-in name.", code="unknown_user")
        self.admin.grant(actor.user_id, project_id, user_id, Role(role))
        return self.admin.members(project_id)

    def revoke(self, actor: Actor, project_id: str, user_id: str, role: str) -> list[Json]:
        self._authorize(actor, project_id, Action.MANAGE_MEMBERS)
        if Role(role) is Role.PROJECT_ADMIN and self.admin.admin_count(project_id) <= 1:
            raise Conflict("A project needs at least one administrator.", code="last_admin")
        self.admin.revoke(actor.user_id, project_id, user_id, Role(role))
        return self.admin.members(project_id)

    def quality(self, actor: Actor, project_id: str) -> Json:
        self._authorize(actor, project_id, Action.VIEW_QUALITY)
        return self.admin.quality(project_id)
