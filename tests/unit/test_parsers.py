import json
from pathlib import Path

import pytest

from sequence_vault.adapters.contracts import schema_errors
from sequence_vault.adapters.parsers.fasta import parse_fasta
from sequence_vault.adapters.parsers.sandbox import SandboxedParser
from sequence_vault.adapters.parsers.text import parse_text
from sequence_vault.application.ports import ParseFailed

CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts"
OPTIONS = {"tracked_changes_view": "not_applicable"}


def blocks(document: dict[str, object]) -> list[tuple[str, str, str, int, int]]:
    return [
        (
            b["block_id"],
            b["type"],
            b["raw_text"],
            b["location"]["line_start"],
            b["location"]["line_end"],
        )
        for b in document["blocks"]  # type: ignore[attr-defined]
    ]


def test_fasta_keeps_headers_bodies_and_line_numbers() -> None:
    data = b">sp|P1|A1 heavy chain\nMKTAY\r\nIAKQR\n\n>B2\n>C3\nMKW\n"
    document = parse_fasta(data, file_id="f", run_id="r", parse_options=OPTIONS)
    assert schema_errors(CONTRACTS, "document-ir", document) == []
    assert blocks(document) == [
        ("h0", "fasta_header", "sp|P1|A1 heavy chain", 1, 1),
        ("s0", "sequence", "MKTAY\nIAKQR", 2, 3),
        ("h1", "fasta_header", "B2", 5, 5),
        ("h2", "fasta_header", "C3", 6, 6),
        ("s2", "sequence", "MKW", 7, 7),
    ]


def test_fasta_preamble_is_reported_as_unresolved() -> None:
    document = parse_fasta(b"Note\n>A\nMKT\n", file_id="f", run_id="r", parse_options=OPTIONS)
    assert document["coverage"]["unresolved_blocks"] == ["t0"]


def test_text_paragraphs_keep_code_points_for_chinese_text() -> None:
    data = "名称：RSPO3\nMKTAYIAKQR\n\n备注\n".encode()
    document = parse_text(data, file_id="f", run_id="r", parse_options=OPTIONS)
    assert schema_errors(CONTRACTS, "document-ir", document) == []
    assert blocks(document) == [
        ("p0", "paragraph", "名称：RSPO3\nMKTAYIAKQR", 1, 2),
        ("p1", "paragraph", "备注", 4, 4),
    ]


def test_sandbox_parses_in_a_separate_process() -> None:
    document = SandboxedParser().parse(
        "fasta", b">A\nMKT\n", file_id="f", run_id="r", parse_options=OPTIONS
    )
    assert json.dumps(document)
    assert document["blocks"][1]["raw_text"] == "MKT"


def test_sandbox_reports_parser_failures_and_limits() -> None:
    with pytest.raises(ParseFailed) as unsupported:
        SandboxedParser().parse("docx", b"x", file_id="f", run_id="r", parse_options=OPTIONS)
    assert unsupported.value.code == "unsupported_format"
    with pytest.raises(ParseFailed) as limited:
        SandboxedParser(memory_mb=40).parse(
            "fasta", b">A\n" + b"M" * 30_000_000, file_id="f", run_id="r", parse_options=OPTIONS
        )
    assert limited.value.code in {"parser_memory_limit", "parser_crash"}
