"""Character classes behind QC03-QC06, applied to a normalized sequence."""

from dataclasses import dataclass

STANDARD_RESIDUES = frozenset("ACDEFGHIKLMNPQRSTVWY")
EXTENDED_RESIDUES = frozenset("BZJXUO")
ELLIPSIS_CHARACTERS = frozenset("…⋯")  # … and ⋯ (common in Chinese documents)
GAP_OR_STOP_CHARACTERS = frozenset("*-")


@dataclass(frozen=True, slots=True)
class CharacterFindings:
    """Positions in the normalized sequence, grouped by the rule they trigger."""

    invalid: tuple[int, ...]  # QC03
    extended: tuple[int, ...]  # QC04
    ellipsis: tuple[int, ...]  # QC05
    gaps_and_stops: tuple[int, ...]  # QC06


def scan(sequence: str) -> CharacterFindings:
    """Classify every non-standard character. Two or more dots in a row are an ellipsis;
    a single dot is treated as an alignment gap."""
    invalid: list[int] = []
    extended: list[int] = []
    ellipsis: list[int] = []
    gaps: list[int] = []
    index = 0
    while index < len(sequence):
        character = sequence[index]
        if character == ".":
            end = index
            while end < len(sequence) and sequence[end] == ".":
                end += 1
            (ellipsis if end - index >= 2 else gaps).extend(range(index, end))
            index = end
            continue
        if character in EXTENDED_RESIDUES:
            extended.append(index)
        elif character in ELLIPSIS_CHARACTERS:
            ellipsis.append(index)
        elif character in GAP_OR_STOP_CHARACTERS:
            gaps.append(index)
        elif character not in STANDARD_RESIDUES:
            invalid.append(index)
        index += 1
    return CharacterFindings(tuple(invalid), tuple(extended), tuple(ellipsis), tuple(gaps))


def describe(sequence: str, positions: tuple[int, ...]) -> str:
    """List distinct characters with code points so look-alikes are visible to reviewers."""
    seen = dict.fromkeys(sequence[position] for position in positions)
    return ", ".join(f"{character!r} (U+{ord(character):04X})" for character in seen)
