"""QC02: deterministic whitespace and case normalization with a transformation log."""

from dataclasses import dataclass

_ASCII_LOWER = frozenset("abcdefghijklmnopqrstuvwxyz")


@dataclass(frozen=True, slots=True)
class Transformation:
    rule_id: str
    operation: str
    reason: str
    positions: tuple[int, ...]
    """Code-point positions in the raw text."""


@dataclass(frozen=True, slots=True)
class Normalized:
    sequence: str
    raw_positions: tuple[int, ...]
    """raw_positions[i] is the raw-text position that produced sequence[i]."""
    transformations: tuple[Transformation, ...]


def normalize(raw: str) -> Normalized:
    """Drop whitespace and upper-case ASCII letters; leave every other character alone.

    Only ASCII letters are upper-cased: ``str.upper`` can change length (``"ß"`` becomes
    ``"SS"``), which would break the position mapping and hide a look-alike character.
    """
    removed: list[int] = []
    uppercased: list[int] = []
    characters: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(raw):
        if character.isspace():
            removed.append(index)
            continue
        if character in _ASCII_LOWER:
            uppercased.append(index)
            character = character.upper()
        characters.append(character)
        positions.append(index)
    transformations: list[Transformation] = []
    if removed:
        transformations.append(
            Transformation(
                "QC02",
                "remove_whitespace",
                "Whitespace and line breaks are not residues.",
                tuple(removed),
            )
        )
    if uppercased:
        transformations.append(
            Transformation(
                "QC02",
                "uppercase",
                "Residue letters are stored in upper case.",
                tuple(uppercased),
            )
        )
    return Normalized("".join(characters), tuple(positions), tuple(transformations))
