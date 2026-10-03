"""The domain must reproduce the synthetic contract examples exactly."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from sequence_vault.application.contract_mapping import (
    blocks_from_document_ir,
    candidate_to_wire,
    context_for,
    parser_delimited,
    records_from_extraction,
)
from sequence_vault.domain.candidate import Candidate
from sequence_vault.domain.extraction import check_extraction
from sequence_vault.domain.qc.engine import evaluate_spans
from sequence_vault.domain.qc.registry import QcRegistry

CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts"


def load(relative: str) -> Any:
    return json.loads((CONTRACTS / relative).read_text(encoding="utf-8"))


def candidate_validator() -> Draft202012Validator:
    schemas = {
        path.name: load(f"schemas/v1/{path.name}") for path in (CONTRACTS / "schemas/v1").iterdir()
    }
    registry: Registry[Any] = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    return Draft202012Validator(schemas["candidate.schema.json"], registry=registry)


def test_synthetic_fasta_example_round_trips(registry: QcRegistry) -> None:
    document = load("examples/document-ir.json")
    extraction = load("examples/extraction-result.json")
    expected = load("examples/candidate.json")

    blocks = blocks_from_document_ir(document)
    records = records_from_extraction(extraction)
    assert check_extraction(blocks, records) == ()

    index = expected["extraction_record_index"]
    record = records[index]
    qc = evaluate_spans(registry, blocks, record.spans, context_for(record, document))
    candidate = Candidate.extracted(
        expected["candidate_id"], extraction["run_id"], record.names, record.spans
    ).validated(qc, parser_delimited=parser_delimited(record, document))

    wire = candidate_to_wire(candidate, index)
    candidate_validator().validate(wire)
    assert wire == expected
