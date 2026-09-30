"""Check repository structure and syntax without application dependencies."""

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "docs/design/Protein_Sequence_App_Design_v1.0_EN.md",
    "apps/web/src/features/review/README.md",
    "services/backend/src/sequence_vault/application/__init__.py",
    "services/backend/src/sequence_vault/workers/__init__.py",
    "database/migrations/README.md",
    "tests/benchmarks/README.md",
    "tools/legacy_migration/README.md",
    "infrastructure/backup/README.md",
)


def read_json(path: Path) -> dict:
    """Reject duplicate keys rather than silently keeping the final value."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def check_references(value, schema_path: Path) -> None:
    """Resolve local schema references; this is not JSON Schema validation."""
    if isinstance(value, list):
        for child in value:
            check_references(child, schema_path)
    elif isinstance(value, dict):
        if "$ref" in value:
            reference = value["$ref"]
            file_name, separator, fragment = reference.partition("#")
            assert ":" not in file_name, f"Remote schema reference: {reference}"
            target = (schema_path.parent / file_name).resolve() if file_name else schema_path
            assert target.is_relative_to(ROOT), f"Reference outside repository: {reference}"
            content = read_json(target)
            if separator and fragment:
                assert fragment.startswith("/"), f"Unsupported pointer: {reference}"
                for token in fragment[1:].split("/"):
                    content = content[token.replace("~1", "/").replace("~0", "~")]
        for child in value.values():
            check_references(child, schema_path)


def check_examples() -> None:
    """Check that the linked synthetic examples describe the same source spans."""
    folder = ROOT / "packages/contracts/examples"
    document = read_json(folder / "document-ir.json")
    extraction = read_json(folder / "extraction-result.json")
    candidate = read_json(folder / "candidate.json")
    assert document["offset_unit"] == "unicode_codepoint"
    assert document["file_id"] == extraction["file_id"]
    assert document["run_id"] == extraction["run_id"] == candidate["run_id"]
    blocks = {block["block_id"]: block for block in document["blocks"]}
    record = extraction["records"][0]
    assert record["candidate_id"] == candidate["candidate_id"]
    assert record["name"] == candidate["name"]
    assert blocks[record["name"]["evidence"]]["raw_text"] == record["name"]["value"]
    assert record["sequence_spans"] == candidate["sequence_spans"]
    reconstructed = ""
    orders = []
    for span in sorted(record["sequence_spans"], key=lambda item: item["order"]):
        text = blocks[span["block_id"]]["raw_text"]
        assert 0 <= span["start"] < span["end"] <= len(text)
        orders.append(span["order"])
        reconstructed += text[span["start"]:span["end"]]
    assert len(orders) == len(set(orders))
    assert reconstructed == candidate["raw_text"] == candidate["normalized_sequence"]
    fixture = ROOT / "tests/fixtures/synthetic.fasta"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == document["source_sha256"]
    assert candidate["status"] == "NEEDS_REVIEW"


def main() -> None:
    for relative_path in REQUIRED:
        assert (ROOT / relative_path).is_file(), f"Missing architecture path: {relative_path}"
    json_paths = sorted((ROOT / "packages/contracts").rglob("*.json"))
    json_paths += sorted((ROOT / "config").glob("*.json"))
    for path in json_paths:
        content = read_json(path)
        if path.name.endswith(".schema.json"):
            assert content["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert content["additionalProperties"] is False
            check_references(content, path)
    python_paths = sorted((ROOT / "services/backend/src").rglob("*.py"))
    python_paths += sorted((ROOT / "scripts").glob("*.py"))
    for path in python_paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    policy = read_json(ROOT / "config/processing-policy.v1.json")
    assert policy["human_confirmation_required"] is True
    assert policy["automatic_ingestion_enabled"] is False
    registry = read_json(ROOT / "config/qc-rules.v1.json")
    assert {rule["rule_id"] for rule in registry["rules"]} == {
        f"QC{number:02}" for number in range(1, 12)
    }
    check_examples()
    print(f"Scaffold checks passed: {len(json_paths)} JSON files, "
          f"{len(python_paths)} Python files, local references and synthetic examples.")
    print("Product behavior and full JSON Schema validation remain pending implementation.")


if __name__ == "__main__":
    main()
