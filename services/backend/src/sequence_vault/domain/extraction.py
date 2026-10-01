"""Extracted records and the cross-field checks JSON Schema cannot express."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sequence_vault.domain.qc.engine import MoleculeType
from sequence_vault.domain.spans import BlockSpan, SequenceSpan, check_spans


@dataclass(frozen=True, slots=True)
class Name:
    value: str
    source: str
    evidence: BlockSpan | None


@dataclass(frozen=True, slots=True)
class ExtractedRecord:
    names: tuple[Name, ...]
    molecule_type_hint: MoleculeType
    spans: tuple[SequenceSpan, ...]
    association_status: str
    observation_kinds: frozenset[str]


def check_extraction(
    blocks: Mapping[str, str], records: Sequence[ExtractedRecord]
) -> tuple[str, ...]:
    """Problems that make an extraction result unusable; an empty tuple means usable.

    Callers allow one controlled repair attempt, then route to human handling.
    """
    problems: list[str] = []
    claimed: list[tuple[int, SequenceSpan]] = []
    for index, record in enumerate(records):
        for name in record.names:
            if name.evidence is None:
                continue
            text = blocks.get(name.evidence.block_id)
            if text is None:
                problems.append(
                    f"record {index}: name evidence block {name.evidence.block_id!r} does not exist"
                )
            elif text[name.evidence.start : name.evidence.end] != name.value:
                problems.append(f"record {index}: name {name.value!r} does not match its evidence")
        if record.spans:
            problems.extend(
                f"record {index}: {problem}" for problem in check_spans(blocks, record.spans)
            )
        claimed.extend((index, span) for span in record.spans)
    for position, (first_index, first) in enumerate(claimed):
        for second_index, second in claimed[position + 1 :]:
            if (
                first_index != second_index
                and first.block_id == second.block_id
                and first.start < second.end
                and second.start < first.end
            ):
                problems.append(
                    f"records {first_index} and {second_index} claim overlapping text "
                    f"in block {first.block_id!r}"
                )
    return tuple(problems)
