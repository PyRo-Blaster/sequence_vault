"""Plain-text reader: one block per blank-line separated paragraph."""

from typing import Any

from sequence_vault.adapters.parsers.decoding import decode
from sequence_vault.adapters.parsers.document import DocumentBuilder, numbered_lines, text_location

VERSION = "text-1"


def parse_text(
    data: bytes, *, file_id: str, run_id: str, parse_options: dict[str, Any]
) -> dict[str, Any]:
    text, encoding = decode(data)
    builder = DocumentBuilder(file_id, run_id, data, VERSION, encoding, parse_options)
    paragraph: list[tuple[int, str]] = []

    def flush() -> None:
        if paragraph:
            raw = "\n".join(line for _, line in paragraph)
            builder.add(
                f"p{len(builder.blocks)}",
                "paragraph",
                raw,
                text_location(paragraph[0][0], paragraph[-1][0]),
            )
            paragraph.clear()

    for number, line in numbered_lines(text):
        if line.strip():
            paragraph.append((number, line))
        else:
            flush()
    flush()
    return builder.build()
