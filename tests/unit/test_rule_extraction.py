from pathlib import Path
from typing import Any

import pytest

from sequence_vault.adapters.contracts import schema_errors
from sequence_vault.adapters.parsers.fasta import parse_fasta
from sequence_vault.adapters.parsers.text import parse_text
from sequence_vault.application.errors import LimitExceeded
from sequence_vault.application.rule_extraction import extract, is_sequence_like

CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts"
OPTIONS = {"tracked_changes_view": "not_applicable"}


def run(data: bytes, name: str, *, fasta: bool = True, **limits: int) -> dict[str, Any]:
    parse = parse_fasta if fasta else parse_text
    document = parse(data, file_id="f", run_id="r", parse_options=OPTIONS)
    result = extract(
        document,
        name,
        max_candidates=limits.get("max_candidates", 1000),
        max_residues=limits.get("max_residues", 100_000),
    )
    assert schema_errors(CONTRACTS, "extraction-result", result) == []
    return result


def summary(result: dict[str, Any]) -> list[tuple[list[tuple[str, str]], str, int]]:
    return [
        (
            [(n["value"], n["source"]) for n in r["names"]],
            r["association_status"],
            len(r["sequence_spans"]),
        )
        for r in result["records"]
    ]


def test_t02_multiple_fasta_records_keep_their_header_names() -> None:
    result = run(b">A1 heavy\nMKTAYIAKQR\n>A2\nMKTAYIAKQW\n", "batch.fasta")
    assert summary(result) == [
        ([("A1", "fasta_header")], "unambiguous", 1),
        ([("A2", "fasta_header")], "unambiguous", 1),
    ]


def test_t09_header_without_sequence_has_no_spans() -> None:
    result = run(b">A1\n>A2\nMKTAYIAKQR\n", "batch.fasta")
    assert summary(result)[0] == ([("A1", "fasta_header")], "unambiguous", 0)


def test_t01_single_unnamed_sequence_uses_the_filename_for_confirmation() -> None:
    result = run(b"MKTAYIAKQRQISFVKSHFSRQ\n", "RSPO3_C07_v2.txt", fasta=False)
    assert summary(result) == [([("RSPO3_C07_v2", "filename")], "ambiguous", 1)]


def test_t05_filename_conflicting_with_body_name_keeps_both() -> None:
    result = run(b">RSPO3_C07\nMKTAYIAKQR\n", "RSPO3_C08.fasta")
    assert summary(result) == [
        ([("RSPO3_C07", "fasta_header"), ("RSPO3_C08", "filename")], "conflicting", 1)
    ]
    same = run(b">RSPO3_C07\nMKTAYIAKQR\n", "rspo3_c07.fasta")
    assert summary(same)[0][1] == "unambiguous"


def test_heading_paragraphs_and_unnamed_multiples() -> None:
    data = "名称：Heavy\nMKTAYIAKQRQISF\n\nLight:\nDIQMTQSPSSLSAS\n\nMKTAYIAKQRWWWW\n".encode()
    result = run(data, "notes.txt", fasta=False)
    assert summary(result) == [
        ([("Heavy", "heading")], "unambiguous", 1),
        ([("Light", "heading")], "unambiguous", 1),
        ([], "ambiguous", 1),
    ]


def test_residue_runs_inside_prose_are_flagged_not_extracted() -> None:
    data = b"The construct MKTAYIAKQRQISFVKSHFSRQ was expressed in CHO cells.\n"
    result = run(data, "notes.txt", fasta=False)
    assert result["records"] == []
    assert result["coverage"]["unresolved_blocks"] == ["p0"]


def test_limits_stop_explicitly() -> None:
    with pytest.raises(LimitExceeded, match="candidates"):
        run(b">A\nMKT\n>B\nMKT\n", "a.fasta", max_candidates=1)
    with pytest.raises(LimitExceeded, match="exceeds"):
        run(b">A\nMKTAYIAKQR\n", "a.fasta", max_residues=5)


def test_sequence_like_ignores_numbers_and_spaces() -> None:
    assert is_sequence_like("1 MKTAYIAKQR 11 QISFVKSHFS")
    assert not is_sequence_like("Purified by affinity chromatography.")


def test_heading_labels_are_not_part_of_the_name() -> None:
    data = "名称：RSPO3 重链\nEVQLVESGGGLVQPGG\n".encode()
    result = run(data, "a.txt", fasta=False)
    name = result["records"][0]["names"][0]
    assert (name["value"], name["evidence"]["start"], name["evidence"]["end"]) == (
        "RSPO3 重链",
        3,
        11,
    )
