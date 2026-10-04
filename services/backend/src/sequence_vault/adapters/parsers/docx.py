"""DOCX reader over the raw OOXML parts.

python-docx hides tracked changes, text boxes and hidden text, which design section 5 requires
the system to report, so this reads word/document.xml directly with a hardened XML parser.
"""

import io
import zipfile
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from sequence_vault.adapters.parsers.document import DocumentBuilder
from sequence_vault.application.ports import ParseFailed

VERSION = "docx-1"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
VIEWS = {"original", "changes_accepted"}
DEFAULT_VIEW = "changes_accepted"


def q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


@dataclass
class Findings:
    tracked_changes: int = 0
    hidden_runs: int = 0
    images: int = 0
    embedded_objects: int = 0
    merged_cells: int = 0
    text_boxes: list[tuple[int, str]] = field(default_factory=list)


class _Reader:
    def __init__(self, view: str, findings: Findings) -> None:
        self.view = view
        self.findings = findings
        self.paragraph_index = 0

    def text(self, element: Any) -> str:
        parts: list[str] = []
        self._walk(element, parts)
        return "".join(parts)

    def _walk(self, element: Any, parts: list[str]) -> None:
        tag = element.tag
        if tag == q("txbxContent"):
            box = "\n".join(t for t in (self.text(p) for p in element.iter(q("p"))) if t.strip())
            if box.strip():
                self.findings.text_boxes.append((self.paragraph_index, box))
            return
        if tag in (q("del"), q("moveFrom")):
            self.findings.tracked_changes += 1
            if self.view != "original":
                return
        elif tag in (q("ins"), q("moveTo")):
            self.findings.tracked_changes += 1
            if self.view == "original":
                return
        elif tag == q("r"):
            properties = element.find(q("rPr"))
            if properties is not None and properties.find(q("vanish")) is not None:
                self.findings.hidden_runs += 1
                return
        elif tag in (q("t"), q("delText")):
            parts.append(element.text or "")
            return
        elif tag == q("tab"):
            parts.append("\t")
            return
        elif tag in (q("br"), q("cr")):
            parts.append("\n")
            return
        elif tag == q("drawing") or tag == q("pict"):
            self.findings.images += 1
        elif tag == q("object"):
            self.findings.embedded_objects += 1
            return
        elif tag == q("p") and parts and not parts[-1].endswith("\n"):
            parts.append("\n")
        for child in element:
            self._walk(child, parts)


def parse_docx(
    data: bytes, *, file_id: str, run_id: str, parse_options: dict[str, Any]
) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = set(archive.namelist())
        root = etree.fromstring(archive.read("word/document.xml"), _parser())
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as error:
        raise ParseFailed("The Word document is damaged.", code="corrupt_document") from error
    requested = parse_options.get("tracked_changes_view", "not_applicable")
    view = requested if requested in VIEWS else DEFAULT_VIEW
    findings = Findings()
    reader = _Reader(view, findings)
    body = root.find(q("body"))
    if body is None:
        raise ParseFailed("The Word document has no body.", code="corrupt_document")

    blocks: list[tuple[str, str, str, dict[str, Any]]] = []
    table_index = 0
    for element in body:
        if element.tag == q("p"):
            text = reader.text(element)
            if text.strip():
                blocks.append(
                    (
                        f"p{reader.paragraph_index}",
                        "paragraph",
                        text,
                        {"kind": "docx_paragraph", "paragraph_index": reader.paragraph_index},
                    )
                )
            reader.paragraph_index += 1
        elif element.tag == q("tbl"):
            for row_index, row in enumerate(element.findall(q("tr"))):
                for column, cell in enumerate(row.findall(q("tc"))):
                    span = cell.find(f"{q('tcPr')}/{q('gridSpan')}")
                    merge = cell.find(f"{q('tcPr')}/{q('vMerge')}")
                    if span is not None or merge is not None:
                        findings.merged_cells += 1
                    text = reader.text(cell).strip("\n")
                    if text.strip():
                        blocks.append(
                            (
                                f"t{table_index}r{row_index}c{column}",
                                "table_cell",
                                text,
                                {
                                    "kind": "docx_table_cell",
                                    "table_index": table_index,
                                    "row": row_index,
                                    "column": column,
                                },
                            )
                        )
            table_index += 1

    tracked = findings.tracked_changes > 0
    options = {"tracked_changes_view": view if tracked else "not_applicable"}
    builder = DocumentBuilder(file_id, run_id, data, VERSION, "utf-8", options)
    for block_id, kind, text, location in blocks:
        builder.add(block_id, kind, text, location)
    for number, (anchor, text) in enumerate(findings.text_boxes):
        block_id = f"x{number}"
        builder.add(block_id, "text", text, {"kind": "docx_paragraph", "paragraph_index": anchor})
    warnings = builder.warnings
    if tracked:
        shown = "original text" if view == "original" else "changes accepted"
        warnings.append(
            f"Tracked changes ({findings.tracked_changes}) are shown with {shown}; "
            "choose the view to use before approving."
        )
    if findings.text_boxes:
        warnings.append(
            f"{len(findings.text_boxes)} text box(es) were read outside the body order."
        )
    if findings.hidden_runs:
        warnings.append(f"{findings.hidden_runs} hidden text run(s) were not read.")
    if findings.images:
        warnings.append(f"{findings.images} image(s) were not read; OCR is not available yet.")
    if findings.embedded_objects or any(n.startswith("word/embeddings/") for n in names):
        warnings.append("Embedded objects were not read.")
    if findings.merged_cells:
        warnings.append(
            f"{findings.merged_cells} merged table cell(s); check row and column pairing."
        )
    if any(n.startswith(("word/header", "word/footer")) for n in names):
        warnings.append("Headers and footers were not read.")
    if "word/comments.xml" in names:
        warnings.append("Comments were not read.")
    if "word/footnotes.xml" in names or "word/endnotes.xml" in names:
        warnings.append("Footnotes and endnotes were not read.")
    return builder.build()
