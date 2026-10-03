"""Smoke test run inside the backend image (CI): imports, bundled files, and a sandboxed
parse under the image's read-only, non-root runtime.

    docker run --rm -i --read-only --tmpfs /tmp IMAGE python - < smoke_image.py
"""

import os

import sequence_vault.entrypoints.api_main
import sequence_vault.entrypoints.worker_main  # noqa: F401
from sequence_vault.adapters.contracts import load_policy, load_registry, schema_errors
from sequence_vault.adapters.parsers.sandbox import SandboxedParser
from sequence_vault.adapters.persistence.migrate import migrations_dir
from sequence_vault.application.ports import DEFAULT_PARSE_OPTIONS
from sequence_vault.settings import REPO_ROOT

assert os.geteuid() != 0, "the image must not run as root"
registry = load_registry(REPO_ROOT / "config")
load_policy(REPO_ROOT / "config")
assert (migrations_dir() / "alembic.ini").exists()
assert (REPO_ROOT / "prompts/extraction/v1/system.md").exists()
document = SandboxedParser().parse(
    "fasta",
    b">A1\nMKTAYIAKQR\n",
    file_id="f1",
    run_id="r1",
    parse_options=dict(DEFAULT_PARSE_OPTIONS),
)
assert schema_errors(REPO_ROOT / "packages/contracts", "document-ir", document) == []
print(f"backend image ok: qc {registry.version}, {len(document['blocks'])} blocks")
