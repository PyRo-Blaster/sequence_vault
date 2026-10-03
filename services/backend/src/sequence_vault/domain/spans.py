"""Evidence spans and deterministic sequence reconstruction.

Offsets are Unicode code points in half-open ranges, which is exactly how Python
indexes ``str``. Sequence text always comes from stored blocks, never from model text.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True, slots=True)
class BlockSpan:
    block_id: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SequenceSpan:
    block_id: str
    start: int
    end: int
    order: int


@dataclass(frozen=True, slots=True)
class Segment:
    """Where one span's characters landed in the reconstructed text."""

    block_id: str
    block_start: int
    text_start: int
    length: int


@dataclass(frozen=True, slots=True)
class Reconstruction:
    text: str
    segments: tuple[Segment, ...]

    def locate(self, position: int) -> tuple[str, int] | None:
        """Map a text position to (block_id, block offset); None for manually typed text."""
        for segment in self.segments:
            if segment.text_start <= position < segment.text_start + segment.length:
                return segment.block_id, segment.block_start + position - segment.text_start
        return None

    def evidence_for(self, positions: Iterable[int]) -> tuple[BlockSpan, ...]:
        """Merge text positions into the fewest contiguous block spans."""
        spans: list[BlockSpan] = []
        for position in sorted(set(positions)):
            located = self.locate(position)
            if located is None:
                continue
            block_id, offset = located
            if spans and spans[-1].block_id == block_id and spans[-1].end == offset:
                spans[-1] = BlockSpan(block_id, spans[-1].start, offset + 1)
            else:
                spans.append(BlockSpan(block_id, offset, offset + 1))
        return tuple(spans)


class InvalidSpans(ValueError):
    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def check_spans(blocks: Mapping[str, str], spans: Sequence[SequenceSpan]) -> tuple[str, ...]:
    """Return every reason the spans cannot be reconstructed; empty when they can."""
    if not spans:
        return ("no sequence spans",)
    problems: list[str] = []
    orders = sorted(span.order for span in spans)
    if orders != list(range(1, len(spans) + 1)):
        problems.append(f"assembly orders must run 1..{len(spans)} without gaps, got {orders}")
    for span in spans:
        text = blocks.get(span.block_id)
        if text is None:
            problems.append(f"unknown block {span.block_id!r}")
        elif not 0 <= span.start < span.end <= len(text):
            problems.append(
                f"span [{span.start}, {span.end}) is outside block {span.block_id!r} "
                f"of length {len(text)}"
            )
    by_position = sorted(spans, key=lambda span: (span.block_id, span.start))
    for previous, current in pairwise(by_position):
        if previous.block_id == current.block_id and current.start < previous.end:
            problems.append(f"overlapping spans in block {current.block_id!r}")
    return tuple(problems)


def reconstruct(blocks: Mapping[str, str], spans: Sequence[SequenceSpan]) -> Reconstruction:
    """Copy span characters out of the blocks in assembly order."""
    problems = check_spans(blocks, spans)
    if problems:
        raise InvalidSpans(problems)
    pieces: list[str] = []
    segments: list[Segment] = []
    cursor = 0
    for span in sorted(spans, key=lambda item: item.order):
        piece = blocks[span.block_id][span.start : span.end]
        segments.append(Segment(span.block_id, span.start, cursor, len(piece)))
        pieces.append(piece)
        cursor += len(piece)
    return Reconstruction("".join(pieces), tuple(segments))


def typed_text(text: str) -> Reconstruction:
    """Wrap manually typed sequence text, which has no block evidence."""
    return Reconstruction(text, ())
