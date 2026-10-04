"""Administration CLI: python -m sequence_vault.entrypoints.admin <command>"""

import argparse
import json
import sys

from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError, IntegrityError, NoResultFound, SQLAlchemyError

from sequence_vault.adapters.persistence.admin import Provisioning
from sequence_vault.adapters.persistence.migrate import upgrade
from sequence_vault.application.authorization import Role
from sequence_vault.settings import Settings

DEV_USERS = [
    ("alice@example.test", "Alice (上传与审核)", [Role.UPLOADER, Role.REVIEWER]),
    ("bob@example.test", "Bob (上传)", [Role.UPLOADER]),
    ("victor@example.test", "Victor (查看)", [Role.VIEWER]),
    ("admin@example.test", "Admin (项目管理员)", [Role.PROJECT_ADMIN, Role.VIEWER]),
]


def openapi() -> dict[str, object]:
    """The OpenAPI document; building the app needs no database connection."""
    from sequence_vault.api.app import create_app
    from sequence_vault.entrypoints.bootstrap import api_services, build

    settings = Settings.from_env(
        {
            "SEQUENCE_VAULT_ENV": "development",
            "SEQUENCE_VAULT_STORAGE": "local",
            "SEQUENCE_VAULT_SCANNER": "development",
            "SEQUENCE_VAULT_LOCAL_STORAGE_DIR": "/tmp/sequence-vault-openapi",
            "SEQUENCE_VAULT_DATABASE_URL": "postgresql+psycopg://openapi@localhost/none",
        }
    )
    return create_app(api_services(build(settings))).openapi()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sequence-vault-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("openapi", help="print the OpenAPI document")
    sub.add_parser("seed-dev", help="create a development tenant, project and users")
    tenant = sub.add_parser("create-tenant")
    tenant.add_argument("--name", required=True)
    project = sub.add_parser("create-project")
    project.add_argument("--tenant", required=True)
    project.add_argument("--name", required=True)
    user = sub.add_parser("add-user")
    user.add_argument("--tenant", required=True)
    user.add_argument("--subject", required=True, help="identity from the sign-in proxy")
    user.add_argument("--name", required=True)
    for command in ("grant", "revoke"):
        role_parser = sub.add_parser(command)
        role_parser.add_argument("--project", required=True)
        role_parser.add_argument("--user", required=True)
        role_parser.add_argument("--role", required=True, choices=[r.value for r in Role])
    args = parser.parse_args(argv)

    if args.command == "openapi":
        json.dump(openapi(), sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    try:
        return _run(args)
    except NoResultFound:
        print("error: no such project", file=sys.stderr)
    except IntegrityError as exc:
        print(f"error: unknown tenant, project or user ({_reason(exc)})", file=sys.stderr)
    except SQLAlchemyError as exc:
        print(f"error: database: {_reason(exc)}", file=sys.stderr)
    return 2


def _reason(exc: SQLAlchemyError) -> str:
    """The driver's first line, without SQL or parameters."""
    cause = exc.orig if isinstance(exc, DBAPIError) else exc
    return str(cause).strip().splitlines()[0] if str(cause).strip() else type(cause).__name__


def _run(args: argparse.Namespace) -> int:
    database_url = Settings.from_env().database_url
    if args.command == "migrate":
        upgrade(database_url)
        return 0
    admin = Provisioning(create_engine(database_url))
    if args.command == "seed-dev":
        if not Settings.from_env().is_development:
            print("seed-dev only runs with SEQUENCE_VAULT_ENV=development", file=sys.stderr)
            return 2
        tenant_id = admin.tenant("Development")
        project_id = admin.project(tenant_id, "演示项目 Demo antibodies")
        for subject, name, roles in DEV_USERS:
            user_id = admin.user(tenant_id, subject, name)
            for role in roles:
                admin.grant(project_id, user_id, role)
        print(json.dumps({"tenant_id": tenant_id, "project_id": project_id}))
    elif args.command == "create-tenant":
        print(admin.tenant(args.name))
    elif args.command == "create-project":
        print(admin.project(args.tenant, args.name))
    elif args.command == "add-user":
        print(admin.user(args.tenant, args.subject, args.name))
    elif args.command == "grant":
        admin.grant(args.project, args.user, Role(args.role))
    elif args.command == "revoke":
        admin.revoke(args.project, args.user, Role(args.role))
    return 0


if __name__ == "__main__":
    sys.exit(main())
