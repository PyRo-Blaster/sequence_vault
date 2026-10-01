"""FASTA reader that keeps exact text, line numbers and code-point offsets."""

from typing import Any

from sequence_vault.adapters.parsers.decoding import decode
from sequence_vault.adapters.parsers.document import DocumentBuilder, numbered_lines, text_location

VERSION = "fasta-1"


def _flush(
    builder: DocumentBuilder, block_id: str, kind: str, lines: list[tuple[int, str]]
) -> None:
    while lines and not lines[0][1].strip():
        lines.pop(0)
    while lines and not lines[-1][1].strip():
        lines.pop()
    if lines:
        raw = "\n".join(line for _, line in lines)
        builder.add(block_id, kind, raw, text_location(lines[0][0], lines[-1][0]))


def parse_fasta(
    data: bytes, *, file_id: str, run_id: str, parse_options: dict[str, Any]
) -> dict[str, Any]:
    text, encoding = decode(data)
    builder = DocumentBuilder(file_id, run_id, data, VERSION, encoding, parse_options)
    preamble: list[tuple[int, str]] = []
    body: list[tuple[int, str]] = []
    record = -1
    for number, line in numbered_lines(text):
        if line.startswith(">"):
            if record < 0:
                _flush(builder, "t0", "text", preamble)
            else:
                _flush(builder, f"s{record}", "sequence", body)
            record += 1
            body = []
            builder.add(f"h{record}", "fasta_header", line[1:], text_location(number, number))
        elif record < 0:
            preamble.append((number, line))
        else:
            body.append((number, line))
    if record >= 0:
        _flush(builder, f"s{record}", "sequence", body)
    else:
        _flush(builder, "t0", "text", preamble)
    if any(block["block_id"] == "t0" for block in builder.blocks):
        builder.warnings.append("Text before the first FASTA header was not treated as a record.")
        builder.unresolved.append("t0")
    return builder.build()
