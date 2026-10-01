"""Import a legacy export and reconcile it (design, "Legacy System Migration").

    uv run python tools/legacy_migration/migrate.py EXPORT.json --project PROJECT_ID \\
        --legacy-project NAME --operator SUBJECT [--dry-run] [--report report.json]

The export is JSON:

    {"source_system": "LIMS", "exported_at": "2026-09-20T10:00:00+00:00",
     "records": [{"legacy_id": "L-1", "project": "Antibodies", "name": "A1",
                  "sequence": "MKT...", "molecule_type": "protein",
                  "created_at": "2019-03-01T08:00:00+00:00", "updated_at": null}],
     "permissions": [{"subject": "alice@corp", "project": "Antibodies", "role": "reviewer"}]}

Uses the same settings as the services (SEQUENCE_VAULT_*). The operator must be an uploader
and reviewer in the project. Exit status: 0 when the reconciliation balances with no hash
mismatches, 1 otherwise, 2 for usage errors. Sequences never appear in the report.
"""

import argparse
import json
import sys
from pathlib import Path

from sequence_vault.adapters.persistence.admin import SqlProjectAdmin
from sequence_vault.application.authorization import Actor
from sequence_vault.application.errors import ApplicationError
from sequence_vault.application.legacy_migration import LegacyMigration
from sequence_vault.entrypoints.bootstrap import build
from sequence_vault.settings import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--project", required=True, help="target project ID")
    parser.add_argument("--legacy-project", required=True, help="project name in the export")
    parser.add_argument("--operator", required=True, help="sign-in subject of the operator")
    parser.add_argument("--dry-run", action="store_true", help="run QC and report; write nothing")
    parser.add_argument("--report", type=Path, help="also write the report to this file")
    args = parser.parse_args(argv)

    container = build(Settings.from_env())
    admin = SqlProjectAdmin(container.engine)
    tenant_id = admin.project_tenant(args.project)
    user_id = None if tenant_id is None else admin.user_in_tenant(tenant_id, args.operator)
    if tenant_id is None or user_id is None:
        print("Unknown project or operator.", file=sys.stderr)
        return 2
    migration = LegacyMigration(
        container.uow, container.store, container.scanner, container.registry
    )
    try:
        report = migration.run(
            Actor(user_id, tenant_id),
            args.project,
            args.export.name,
            args.export.read_bytes(),
            args.legacy_project,
            dry_run=args.dry_run,
        )
    except ApplicationError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["balanced"] and not report["hash_mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
