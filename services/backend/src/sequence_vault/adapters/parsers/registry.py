"""Enabled parsers by detected format. A format is enabled only once its parser meets the
format, security and coverage contracts."""

from collections.abc import Callable
from typing import Any

from sequence_vault.adapters.parsers.docx import parse_docx
from sequence_vault.adapters.parsers.fasta import parse_fasta
from sequence_vault.adapters.parsers.pdf import parse_pdf
from sequence_vault.adapters.parsers.tables import parse_csv, parse_xlsx
from sequence_vault.adapters.parsers.text import parse_text
from sequence_vault.application.ports import ParseFailed

Parser = Callable[..., dict[str, Any]]

PARSERS: dict[str, Parser] = {
    "fasta": parse_fasta,
    "txt": parse_text,
    "csv": parse_csv,
    "xlsx": parse_xlsx,
    "docx": parse_docx,
    "text_pdf": parse_pdf,
}


def enabled_formats() -> frozenset[str]:
    return frozenset(PARSERS)


def parse(
    format: str, data: bytes, *, file_id: str, run_id: str, parse_options: dict[str, Any]
) -> dict[str, Any]:
    parser = PARSERS.get(format)
    if parser is None:
        raise ParseFailed(f"No parser is enabled for {format}.", code="unsupported_format")
    return parser(data, file_id=file_id, run_id=run_id, parse_options=parse_options)
