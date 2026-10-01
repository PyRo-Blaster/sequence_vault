"""Project roles and the actions they allow (design section 2)."""

from collections.abc import Set
from dataclasses import dataclass
from enum import StrEnum

from sequence_vault.application.errors import Forbidden, NotFound


class Role(StrEnum):
    UPLOADER = "uploader"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    PROJECT_ADMIN = "project_admin"


class Action(StrEnum):
    UPLOAD = "upload"
    EDIT = "edit"
    REVIEW = "review"
    COMMIT = "commit"
    VIEW = "view"
    EXPORT = "export"
    MANAGE_MEMBERS = "manage_members"
    VIEW_QUALITY = "view_quality"


PERMISSIONS: dict[Action, frozenset[Role]] = {
    Action.UPLOAD: frozenset({Role.UPLOADER, Role.REVIEWER}),
    Action.EDIT: frozenset({Role.UPLOADER, Role.REVIEWER}),
    Action.REVIEW: frozenset({Role.REVIEWER}),
    Action.COMMIT: frozenset({Role.REVIEWER}),
    Action.VIEW: frozenset(Role),
    Action.EXPORT: frozenset(Role),
    Action.MANAGE_MEMBERS: frozenset({Role.PROJECT_ADMIN}),
    Action.VIEW_QUALITY: frozenset({Role.PROJECT_ADMIN, Role.REVIEWER}),
}


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    tenant_id: str


def authorize(roles: Set[Role], action: Action) -> None:
    """Non-members get NotFound so a project's existence is never disclosed."""
    if not roles:
        raise NotFound("Not found.")
    if not roles & PERMISSIONS[action]:
        raise Forbidden(f"Your project role does not allow {action}.")
