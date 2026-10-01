"""The evaluation tool must pass the synthetic gold set and fail honestly when gold differs."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from sequence_vault.settings import REPO_ROOT

MANIFEST = REPO_ROOT / "tests/fixtures/evaluation/manifest.json"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "evaluate", REPO_ROOT / "tools/evaluation/evaluate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_set_meets_the_acceptance_thresholds() -> None:
    report = load().score(MANIFEST)
    assert report["passed"], report["failures"]
    assert set(report["by_format"]) == {"fasta", "txt", "docx", "xlsx", "csv", "text_pdf"}


def test_wrong_names_missing_records_and_unblocked_cases_fail(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text())
    for entry in manifest["files"]:
        entry["path"] = str(MANIFEST.parent / entry["path"])
    manifest["files"][0]["records"][0]["name"] = "Wrong"
    manifest["files"][0]["records"].append({"name": "Ghost", "sequence": "W" * 40})
    manifest["files"][1]["records"][0]["blocking_rules"] = ["QC05"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    report = load().score(path)
    assert not report["passed"]
    failures = "\n".join(report["failures"])
    assert "name 'Ab1_heavy' != 'Wrong'" in failures
    assert "missed record Ghost" in failures
    assert "expected BLOCK ['QC05']" in failures
    assert report["metrics"]["recall"] < 1
    assert "W" * 20 not in failures  # sequences never reach the report
