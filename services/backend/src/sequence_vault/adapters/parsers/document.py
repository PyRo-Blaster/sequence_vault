"""Build DocumentIR documents (packages/contracts/schemas/v1/document-ir.schema.json)."""

import hashlib
from dataclasses import dataclass, field
from typing import Any

Json = dict[str, Any]


@dataclass
class DocumentBuilder:
    file_id: str
    run_id: str
    source: bytes
    parser_version: str
    source_encoding: str
    parse_options: Json
    blocks: list[Json] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def add(self, block_id: str, kind: str, raw_text: str, location: Json) -> None:
        self.blocks.append(
            {
                "block_id": block_id,
                "type": kind,
                "raw_text": raw_text,
                "location": location,
                "extraction_method": "text_parser",
            }
        )

    def build(self) -> Json:
        return {
            "schema_version": "1.0",
            "file_id": self.file_id,
            "run_id": self.run_id,
            "source_sha256": hashlib.sha256(self.source).hexdigest(),
            "parser_version": self.parser_version,
            "source_encoding": self.source_encoding,
            "parse_options": self.parse_options,
            "offset_unit": "unicode_codepoint",
            "blocks": self.blocks,
            "coverage": {
                "unresolved_blocks": self.unresolved,
                "truncated": False,
                "warnings": self.warnings,
            },
        }


def text_location(line_start: int, line_end: int) -> Json:
    return {"kind": "text", "line_start": line_start, "line_end": line_end}


def numbered_lines(text: str) -> list[tuple[int, str]]:
    """(1-based line number, line without its terminator)."""
    return [(index + 1, line) for index, line in enumerate(text.splitlines())]
