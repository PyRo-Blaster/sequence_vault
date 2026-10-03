"""DOCX, XLSX, CSV and text-PDF parsing plus rule extraction (T03, T04, T06, T07)."""

from typing import Any

import pytest

from sequence_vault.adapters.contracts import schema_errors
from sequence_vault.adapters.parsers.docx import parse_docx
from sequence_vault.adapters.parsers.pdf import MAX_PAGES, parse_pdf
from sequence_vault.adapters.parsers.tables import parse_csv, parse_xlsx
from sequence_vault.application.ports import ParseFailed
from sequence_vault.application.rule_extraction import extract
from sequence_vault.settings import REPO_ROOT
from tests.fixtures import builders

CONTRACTS = REPO_ROOT / "packages/contracts"
OPTIONS = {"tracked_changes_view": "not_applicable"}
HEAVY = "EVQLVESGGGLVQPGGSLRLSCAASGFTFS"
LIGHT = "DIQMTQSPSSLSASVGDRVTITCRASQ"


def parse(parser: Any, data: bytes, **options: str) -> dict[str, Any]:
    document: dict[str, Any] = parser(
        data, file_id="f", run_id="r", parse_options={**OPTIONS, **options}
    )
    assert schema_errors(CONTRACTS, "document-ir", document) == []
    return document


def records(document: dict[str, Any], file_name: str = "file.docx") -> list[dict[str, Any]]:
    result = extract(document, file_name, max_candidates=1000, max_residues=100_000)
    assert schema_errors(CONTRACTS, "extraction-result", result) == []
    out: list[dict[str, Any]] = result["records"]
    return out


def text(document: dict[str, Any], block_id: str) -> str:
    return str(next(b["raw_text"] for b in document["blocks"] if b["block_id"] == block_id))


def test_t03_word_names_and_sequences_split_over_paragraphs() -> None:
    data = builders.docx(["Antibody A1:", HEAVY[:15], HEAVY[15:], "", "Antibody B2", LIGHT])
    document = parse(parse_docx, data)
    found = records(document, "batch.docx")
    assert [(r["names"][0]["value"], len(r["sequence_spans"])) for r in found] == [
        ("Antibody A1", 2),
        ("Antibody B2", 1),
    ]
    assert found[0]["observations"][0]["kind"] == "cross_block_join"
    assert all(r["association_status"] == "unambiguous" for r in found)


def test_t04_heavy_and_light_chains_stay_separate() -> None:
    data = builders.docx([[["Clone", "重链", "轻链"], ["Ab1", HEAVY, LIGHT]]])
    found = records(parse(parse_docx, data))
    assert [(r["names"][0]["value"], r["association_status"]) for r in found] == [
        ("Ab1", "ambiguous"),
        ("Ab1", "ambiguous"),
    ]
    assert [r["observations"][0]["message"] for r in found] == [
        "Chain column '重链': add the chain label to the name.",
        "Chain column '轻链': add the chain label to the name.",
    ]


def test_t07_tracked_changes_text_boxes_and_hidden_text_are_reported() -> None:
    runs = [
        ("t", "MKTAYIAK"),
        ("ins", "QR"),
        ("del", "WW"),
        ("hidden", "SECRET"),
        ("textbox", "NOTE"),
    ]
    data = builders.docx(["Construct", runs], extra_parts={"word/header1.xml": b"<x/>"})
    accepted = parse(parse_docx, data)
    assert text(accepted, "p1") == "MKTAYIAKQR"
    assert accepted["parse_options"] == {"tracked_changes_view": "changes_accepted"}
    original = parse(parse_docx, data, tracked_changes_view="original")
    assert text(original, "p1") == "MKTAYIAKWW"
    assert text(original, "x0") == "NOTE"
    warnings = " ".join(accepted["coverage"]["warnings"])
    for expected in ("Tracked changes (2)", "text box", "hidden text", "Headers and footers"):
        assert expected in warnings


def test_docx_parser_refuses_entity_expansion() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "AAAAAAAAAA">]>'
        f'<w:document xmlns:w="{builders.W_NS}"><w:body><w:p><w:r><w:t>&a;</w:t></w:r>'
        "</w:p></w:body></w:document>"
    )
    data = builders.docx([])
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, "w") as target:
        for item in source.infolist():
            target.writestr(
                item, bomb if item.filename == "word/document.xml" else source.read(item)
            )
    document = parse(parse_docx, buffer.getvalue())
    assert "AAAAAAAAAA" not in str(document["blocks"])


def test_xlsx_headers_pending_names_formulas_and_hidden_sheets() -> None:
    data = builders.xlsx(
        {
            "序列表": [
                ["名称", "氨基酸序列"],
                ["A1", HEAVY],
                ["A2", None],
                ["A3", '=CONCAT("MK","TAYIAKQRQ")'],
            ],
            "隐藏": [["note"]],
        },
        hidden=("隐藏",),
    )
    document = parse(parse_xlsx, data)
    found = records(document, "batch.xlsx")
    assert [(r["names"][0]["value"], len(r["sequence_spans"])) for r in found] == [
        ("A1", 1),
        ("A2", 0),
    ]
    assert document["coverage"]["unresolved_blocks"] == ["s0r3c1"]
    warnings = " ".join(document["coverage"]["warnings"])
    assert "formula" in warnings and "Hidden worksheets were read: 隐藏" in warnings
    location = next(b["location"] for b in document["blocks"] if b["block_id"] == "s0r1c1")
    assert location == {
        "kind": "spreadsheet_cell",
        "worksheet": "序列表",
        "cell": "B2",
        "row": 1,
        "column": 1,
    }


def test_csv_rows_pair_names_with_sequences() -> None:
    document = parse(parse_csv, f"name,sequence\nA1,{HEAVY}\nB2,{LIGHT}\n".encode())
    assert [(r["names"][0]["value"], r["association_status"]) for r in records(document)] == [
        ("A1", "unambiguous"),
        ("B2", "unambiguous"),
    ]


def test_explicit_sequence_columns_keep_short_values_for_qc() -> None:
    document = parse(parse_csv, b"name,sequence\nAb1,ACDE\nAb2,\nAb3,see attached\n")
    assert [(r["names"][0]["value"], len(r["sequence_spans"])) for r in records(document)] == [
        ("Ab1", 1),
        ("Ab2", 0),
        ("Ab3", 1),
    ]


def test_t06_pdf_numbering_and_page_headers_are_kept_for_qc() -> None:
    page = [
        (72, 800, "Confidential draft - page 1"),
        (72, 700, "RSPO3 heavy chain"),
        (72, 686, "1 EVQLVESGGG LVQPGGSLRL"),
        (72, 672, "21 SCAASGFTFS SYAMS"),
    ]
    document = parse(parse_pdf, builders.pdf([page]))
    assert [b["raw_text"] for b in document["blocks"]] == [
        "Confidential draft - page 1",
        "RSPO3 heavy chain\n1 EVQLVESGGG LVQPGGSLRL\n21 SCAASGFTFS SYAMS",
    ]
    assert document["blocks"][1]["location"]["page"] == 1
    (record,) = records(document, "notes.pdf")
    assert record["names"][0]["value"] == "RSPO3 heavy chain"


def test_pdf_page_limit_and_damage_fail_explicitly() -> None:
    with pytest.raises(ParseFailed) as limit:
        parse_pdf(
            builders.pdf([[(72, 700, "x")]] * (MAX_PAGES + 1)),
            file_id="f",
            run_id="r",
            parse_options=OPTIONS,
        )
    assert limit.value.code == "pdf_page_limit"
    with pytest.raises(ParseFailed) as damaged:
        parse_pdf(b"%PDF-1.4 garbage", file_id="f", run_id="r", parse_options=OPTIONS)
    assert damaged.value.code == "corrupt_document"


def test_pdf_page_limit_mirrors_the_policy() -> None:
    import json

    policy = json.loads((REPO_ROOT / "config/processing-policy.v1.json").read_text())
    assert policy["limits"]["max_pdf_pages"] == MAX_PAGES
