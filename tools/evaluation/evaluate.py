"""Frozen-set evaluation (design section 10).

    uv run python tools/evaluation/evaluate.py MANIFEST.json [--report report.md]

The manifest lists files with gold annotations:

    {"set": "name", "files": [{"path": "relative/to/manifest.docx", "format": "docx",
      "standard": false, "records": [{"name": "A1", "sequence": "MKT...",
      "blocking_rules": []}]}]}

Each file runs through the same parser, rule extraction and QC as production (no database,
no model). Metrics use exact whole-sequence equality, count missed records in recall, and
check that every gold BLOCK expectation is intercepted. Sequences never appear in the report.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sequence_vault.adapters.contracts import load_registry
from sequence_vault.adapters.parsers.registry import parse
from sequence_vault.adapters.security.filetype import ContentTypeDetector
from sequence_vault.application.contract_mapping import context_for, records_from_extraction
from sequence_vault.application.rule_extraction import extract
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.qc.engine import evaluate_spans
from sequence_vault.domain.qc.registry import Severity
from sequence_vault.settings import REPO_ROOT

THRESHOLDS = {"standard_exact": 1.0, "sequence_accuracy": 0.99, "recall": 0.98, "names": 0.98}


@dataclass
class Found:
    sequence: str
    name: str | None
    blocking: set[str]


@dataclass
class Tally:
    gold: int = 0
    found: int = 0
    matched: int = 0
    exact: int = 0
    names: int = 0
    block_expected: int = 0
    block_caught: int = 0
    files: int = 0
    failures: list[str] = field(default_factory=list)


def run_file(path: Path) -> list[Found]:
    data = path.read_bytes()
    detection = ContentTypeDetector().detect(data, path.name)
    if detection.format is None:
        raise ValueError(f"{path.name}: rejected ({detection.reason})")
    document = parse(
        detection.format,
        data,
        file_id="eval",
        run_id="eval",
        parse_options={"tracked_changes_view": "not_applicable"},
    )
    result = extract(document, path.name, max_candidates=1000, max_residues=100_000)
    registry = load_registry(REPO_ROOT / "config")
    blocks = {b["block_id"]: b["raw_text"] for b in document["blocks"]}
    found = []
    for record in records_from_extraction(result):
        qc = evaluate_spans(registry, blocks, record.spans, context_for(record, document))
        candidate = Candidate.extracted("c", "eval", record.names, record.spans)
        name = candidate.name.value if candidate.name else None
        sequence = qc.normalized.sequence if qc.normalized else ""
        found.append(Found(sequence, name, set(qc.rule_ids(Severity.BLOCK))))
    return found


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    common = sum(1 for x, y in zip(a, b, strict=False) if x == y)
    return common / max(len(a), len(b))


def score(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tallies: dict[str, Tally] = {}
    standard = Tally()
    for entry in manifest["files"]:
        tally = tallies.setdefault(entry["format"], Tally())
        tally.files += 1
        found = run_file(manifest_path.parent / entry["path"])
        tally.found += len(found)
        unmatched = list(found)
        for gold in entry["records"]:
            tally.gold += 1
            if standard_file := entry.get("standard", False):
                standard.gold += 1
            if gold.get("blocking_rules"):
                tally.block_expected += 1
            best = max(
                unmatched, key=lambda f: _similarity(f.sequence, gold["sequence"]), default=None
            )
            if best is None or _similarity(best.sequence, gold["sequence"]) < 0.5:
                tally.failures.append(f"{entry['path']}: missed record {gold.get('name')}")
                continue
            unmatched.remove(best)
            tally.matched += 1
            if best.sequence == gold["sequence"]:
                tally.exact += 1
                if standard_file:
                    standard.exact += 1
            else:
                digest = hashlib.sha256(gold["sequence"].encode()).hexdigest()[:8]
                tally.failures.append(f"{entry['path']}: sequence differs (gold {digest})")
            if best.name == gold.get("name"):
                tally.names += 1
            else:
                tally.failures.append(
                    f"{entry['path']}: name {best.name!r} != {gold.get('name')!r}"
                )
            if gold.get("blocking_rules"):
                if set(gold["blocking_rules"]) <= best.blocking:
                    tally.block_caught += 1
                else:
                    tally.failures.append(
                        f"{entry['path']}: expected BLOCK {gold['blocking_rules']}"
                    )
    total = Tally()
    for tally in tallies.values():
        for key in (
            "gold",
            "found",
            "matched",
            "exact",
            "names",
            "block_expected",
            "block_caught",
            "files",
        ):
            setattr(total, key, getattr(total, key) + getattr(tally, key))
        total.failures += tally.failures

    def ratio(numerator: int, denominator: int) -> float:
        return 1.0 if denominator == 0 else numerator / denominator

    metrics = {
        "sequence_accuracy": ratio(total.exact, total.matched),
        "recall": ratio(total.matched, total.gold),
        "names": ratio(total.names, total.matched),
        "standard_exact": ratio(standard.exact, standard.gold),
        "block_interception": ratio(total.block_caught, total.block_expected),
    }
    passed = (
        all(metrics[k] >= v for k, v in THRESHOLDS.items()) and metrics["block_interception"] == 1.0
    )
    return {
        "set": manifest.get("set"),
        "metrics": metrics,
        "passed": passed,
        "by_format": {
            fmt: {
                "files": t.files,
                "gold_records": t.gold,
                "found": t.found,
                "exact": t.exact,
                "names": t.names,
                "recall": ratio(t.matched, t.gold),
            }
            for fmt, t in sorted(tallies.items())
        },
        "failures": total.failures,
    }


def markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lines = [
        f"# Evaluation: {report['set']}",
        "",
        f"Result: **{'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "| Metric | Value | Threshold |",
        "| --- | --- | --- |",
        f"| Whole-sequence accuracy | {m['sequence_accuracy']:.2%} | ≥ 99% |",
        f"| Record recall (misses included) | {m['recall']:.2%} | ≥ 98% |",
        f"| Name association accuracy | {m['names']:.2%} | ≥ 98% |",
        f"| Standard FASTA exact | {m['standard_exact']:.2%} | 100% |",
        f"| BLOCK cases intercepted | {m['block_interception']:.2%} | 100% |",
        "",
        "| Format | Files | Gold records | Found | Exact | Names | Recall |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for fmt, t in report["by_format"].items():
        lines.append(
            f"| {fmt} | {t['files']} | {t['gold_records']} | {t['found']} | {t['exact']} "
            f"| {t['names']} | {t['recall']:.0%} |"
        )
    if report["failures"]:
        lines += ["", "## Failures", "", *[f"- {f}" for f in report["failures"]]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = score(args.manifest)
    text = markdown(report)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
