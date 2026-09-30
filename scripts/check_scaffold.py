"""Check repository structure, syntax and draft contracts without application code."""

import ast
import copy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "packages/contracts/schemas/v1"
REQUIRED = (
    "docs/design/Protein_Sequence_App_Design_v1.0_EN.md",
    "packages/contracts/schemas/v1/common.schema.json",
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


def schema_validators() -> dict[str, Draft202012Validator]:
    """Build validators whose relative references resolve to sibling schema files."""
    schemas = {path.name: read_json(path) for path in sorted(SCHEMAS.glob("*.schema.json"))}
    registry = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    return {name: Draft202012Validator(schema, registry=registry)
            for name, schema in schemas.items()}


def expect_invalid(validator: Draft202012Validator, instance: dict, reason: str) -> None:
    assert not validator.is_valid(instance), f"Schema accepted {reason}"


def check_boundaries(validators: dict, document: dict, extraction: dict) -> None:
    """Check that the schemas reject states the design forbids."""
    result = validators["extraction-result.schema.json"]
    changed = copy.deepcopy(extraction)
    changed["records"][0]["candidate_id"] = "model_chosen"
    expect_invalid(result, changed, "a model-assigned candidate ID")
    changed = copy.deepcopy(extraction)
    changed["records"][0]["observations"] = [
        {"kind": "possible_truncation", "message": "m", "evidence": [], "severity": "INFO"}
    ]
    expect_invalid(result, changed, "a model-assigned severity")
    changed = copy.deepcopy(extraction)
    changed["records"][0]["names"][0]["source"] = "filename"
    expect_invalid(result, changed, "a filename name with block evidence")
    changed = copy.deepcopy(extraction)
    changed["records"][0]["names"][0]["evidence"] = None
    expect_invalid(result, changed, "a FASTA header name without evidence")
    changed = copy.deepcopy(document)
    changed["blocks"][0]["location"] = {"kind": "spreadsheet_cell", "worksheet": "Sheet1"}
    expect_invalid(validators["document-ir.schema.json"], changed,
                   "a spreadsheet location without a cell address")


def check_examples(validators: dict, registry: dict) -> None:
    """Check that the linked synthetic examples are valid and describe the same source spans."""
    folder = ROOT / "packages/contracts/examples"
    document = read_json(folder / "document-ir.json")
    extraction = read_json(folder / "extraction-result.json")
    candidate = read_json(folder / "candidate.json")
    for schema_name, example in (
        ("document-ir.schema.json", document),
        ("extraction-result.schema.json", extraction),
        ("candidate.schema.json", candidate),
    ):
        validators[schema_name].validate(example)
    assert document["file_id"] == extraction["file_id"]
    assert document["run_id"] == extraction["run_id"] == candidate["run_id"]
    blocks = {block["block_id"]: block for block in document["blocks"]}
    assert len(blocks) == len(document["blocks"]), "Duplicate block IDs"
    for block in document["blocks"]:
        location = block["location"]
        if location["kind"] == "text":
            assert location["line_start"] <= location["line_end"]

    def span_text(span: dict) -> str:
        text = blocks[span["block_id"]]["raw_text"]
        assert 0 <= span["start"] < span["end"] <= len(text), f"Span out of range: {span}"
        return text[span["start"]:span["end"]]

    record = extraction["records"][candidate["extraction_record_index"]]
    assert candidate["extracted_names"] == record["names"]
    assert candidate["name"] in record["names"]
    for name in record["names"]:
        if name["evidence"] is not None:
            assert span_text(name["evidence"]) == name["value"]
    assert record["sequence_spans"] == candidate["sequence_spans"]
    spans = sorted(record["sequence_spans"], key=lambda item: item["order"])
    assert [span["order"] for span in spans] == list(range(1, len(spans) + 1))
    reconstructed = "".join(span_text(span) for span in spans)
    assert reconstructed == candidate["raw_text"] == candidate["normalized_sequence"]
    severities = {rule["rule_id"]: rule["severity"] for rule in registry["rules"]}
    assert candidate["qc_version"] == registry["qc_version"]
    for issue in candidate["issues"]:
        assert severities[issue["rule_id"]] == issue["severity"], f"Severity drift: {issue}"
    fixture = ROOT / "tests/fixtures/synthetic.fasta"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == document["source_sha256"]
    assert candidate["status"] == "NEEDS_REVIEW"
    check_boundaries(validators, document, extraction)


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
    assert registry["generic_block_override_allowed"] is False
    for rule in registry["rules"]:
        assert rule["allowed_resolutions"], f"No resolutions for {rule['rule_id']}"
        assert not {"ignore", "acknowledge", "override"} & set(rule["allowed_resolutions"])
    validators = schema_validators()
    check_examples(validators, registry)
    print(f"Scaffold checks passed: {len(json_paths)} JSON files, "
          f"{len(python_paths)} Python files, schema validation and synthetic examples.")
    print("Product behavior and backend cross-field validation remain pending implementation.")


if __name__ == "__main__":
    main()
