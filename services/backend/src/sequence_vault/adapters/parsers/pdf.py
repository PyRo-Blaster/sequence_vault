"""Text PDF reader: words grouped into lines and paragraphs with page coordinates.
Scanned pages and uncertain reading order are reported, never guessed (design section 5)."""

import io
import statistics
from typing import Any

import pdfplumber

from sequence_vault.adapters.parsers.document import DocumentBuilder
from sequence_vault.application.ports import ParseFailed

VERSION = "pdf-1"
MAX_PAGES = 100  # mirrors config/processing-policy.v1.json limits.max_pdf_pages
LINE_TOLERANCE = 3.0


def _lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _paragraphs(lines: list[list[dict[str, Any]]]) -> list[list[list[dict[str, Any]]]]:
    """Split lines where the vertical gap exceeds 1.6 line heights."""
    heights = [line[0]["bottom"] - line[0]["top"] for line in lines]
    gap_limit = 1.6 * (statistics.median(heights) if heights else 10)
    paragraphs: list[list[list[dict[str, Any]]]] = []
    for line in lines:
        if paragraphs and line[0]["top"] - paragraphs[-1][-1][0]["bottom"] <= gap_limit:
            paragraphs[-1].append(line)
        else:
            paragraphs.append([line])
    return paragraphs


def parse_pdf(
    data: bytes, *, file_id: str, run_id: str, parse_options: dict[str, Any]
) -> dict[str, Any]:
    builder = DocumentBuilder(file_id, run_id, data, VERSION, "pdf-text", parse_options)
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as error:  # pdfminer raises many types for damaged or encrypted files
        raise ParseFailed("The PDF is damaged or encrypted.", code="corrupt_document") from error
    with pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ParseFailed(f"PDFs are limited to {MAX_PAGES} pages.", code="pdf_page_limit")
        scanned: list[int] = []
        columns: list[int] = []
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            if not words:
                if page.images:
                    scanned.append(page_number)
                continue
            lines = _lines(words)
            starts = [line[0]["x0"] for line in lines]
            if (
                sum(1 for x in starts if x > page.width * 0.45) >= 3
                and sum(1 for x in starts if x < page.width * 0.25) >= 3
            ):
                columns.append(page_number)
            for paragraph in _paragraphs(lines):
                text = "\n".join(" ".join(w["text"] for w in line) for line in paragraph)
                every = [w for line in paragraph for w in line]
                bbox = [
                    round(min(w["x0"] for w in every), 1),
                    round(min(w["top"] for w in every), 1),
                    round(max(w["x1"] for w in every), 1),
                    round(max(w["bottom"] for w in every), 1),
                ]
                builder.add(
                    f"g{page_number}p{len(builder.blocks)}",
                    "paragraph",
                    text,
                    {"kind": "pdf_region", "page": page_number, "bbox": bbox},
                )
    if scanned:
        builder.warnings.append(f"Scanned page(s) without text were not read: {scanned}.")
    if columns:
        builder.warnings.append(
            f"Possible multi-column layout on page(s) {columns}; check reading order."
        )
    return builder.build()
