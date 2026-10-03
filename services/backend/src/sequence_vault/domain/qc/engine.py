"""Run every QC rule against one candidate and report issues with block evidence."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sequence_vault.domain.normalization import Normalized, normalize
from sequence_vault.domain.qc.characters import describe, scan
from sequence_vault.domain.qc.registry import Issue, QcRegistry, Severity
from sequence_vault.domain.spans import (
    BlockSpan,
    Reconstruction,
    SequenceSpan,
    check_spans,
    reconstruct,
    typed_text,
)

NUCLEOTIDE_LETTERS = frozenset("ACGTUN")


class MoleculeType(StrEnum):
    PROTEIN = "protein"
    NUCLEIC_ACID = "nucleic_acid"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """Facts about a candidate that QC needs besides its characters."""

    name_count: int
    association_status: str
    observation_kinds: frozenset[str]
    molecule_type_hint: MoleculeType
    coverage_risk: bool
    """True when the document has unresolved blocks or coverage warnings, or any span
    comes from OCR or manual transcription."""
    declared_fragment: bool = False


@dataclass(frozen=True, slots=True)
class QcResult:
    qc_version: str
    raw_text: str
    normalized: Normalized | None
    molecule_type: MoleculeType
    issues: tuple[Issue, ...]

    @property
    def blocked(self) -> bool:
        return any(issue.severity is Severity.BLOCK for issue in self.issues)

    def rule_ids(self, severity: Severity) -> frozenset[str]:
        return frozenset(issue.rule_id for issue in self.issues if issue.severity is severity)


def classify(sequence: str, hint: MoleculeType, observation_kinds: frozenset[str]) -> MoleculeType:
    """Protein only when letters prove it and nothing suggests nucleic acid (QC11)."""
    letters = {character for character in sequence if character.isalpha()}
    if not letters or letters <= NUCLEOTIDE_LETTERS:
        return MoleculeType.UNCERTAIN
    if hint is not MoleculeType.PROTEIN or "possible_nucleic_acid" in observation_kinds:
        return MoleculeType.UNCERTAIN
    return MoleculeType.PROTEIN


def evaluate_spans(
    registry: QcRegistry,
    blocks: Mapping[str, str],
    spans: Sequence[SequenceSpan],
    context: ExtractionContext,
) -> QcResult:
    problems = check_spans(blocks, spans)
    if problems:
        issues = [registry.issue("QC01", "; ".join(problems))]
        issues.extend(_context_issues(registry, context))
        return QcResult(registry.version, "", None, MoleculeType.UNCERTAIN, tuple(issues))
    return _evaluate(registry, reconstruct(blocks, spans), context)


def evaluate_typed(registry: QcRegistry, text: str, context: ExtractionContext) -> QcResult:
    """QC for a manually typed sequence; issues carry no block evidence."""
    return _evaluate(registry, typed_text(text), context)


def _evaluate(
    registry: QcRegistry, rebuilt: Reconstruction, context: ExtractionContext
) -> QcResult:
    normalized = normalize(rebuilt.text)
    sequence = normalized.sequence

    def evidence(positions: Iterable[int]) -> tuple[BlockSpan, ...]:
        return rebuilt.evidence_for(normalized.raw_positions[position] for position in positions)

    issues: list[Issue] = []
    if not sequence:
        issues.append(registry.issue("QC01", "The referenced text contains no residues."))
    for change in normalized.transformations:
        issues.append(
            registry.issue(
                "QC02",
                f"{change.operation}: {len(change.positions)} position(s). {change.reason}",
                rebuilt.evidence_for(change.positions),
            )
        )
    found = scan(sequence)
    if found.invalid:
        issues.append(
            registry.issue(
                "QC03",
                "Characters outside the protein alphabet: " + describe(sequence, found.invalid),
                evidence(found.invalid),
            )
        )
    if found.extended:
        issues.append(
            registry.issue(
                "QC04",
                "Extended residue codes need confirmation: " + describe(sequence, found.extended),
                evidence(found.extended),
            )
        )
    if found.ellipsis:
        issues.append(
            registry.issue("QC05", "Ellipsis marks omitted residues.", evidence(found.ellipsis))
        )
    if found.gaps_and_stops:
        issues.append(
            registry.issue(
                "QC06",
                "Stop or gap characters need an explicit transformation: "
                + describe(sequence, found.gaps_and_stops),
                evidence(found.gaps_and_stops),
            )
        )
    issues.extend(_context_issues(registry, context))
    molecule_type = classify(sequence, context.molecule_type_hint, context.observation_kinds)
    if sequence and molecule_type is not MoleculeType.PROTEIN:
        issues.append(
            registry.issue("QC11", "Confirm the molecule type; only proteins can be published.")
        )
    return QcResult(registry.version, rebuilt.text, normalized, molecule_type, tuple(issues))


def _context_issues(registry: QcRegistry, context: ExtractionContext) -> list[Issue]:
    kinds = context.observation_kinds
    issues: list[Issue] = []
    if "possible_truncation" in kinds and not context.declared_fragment:
        issues.append(registry.issue("QC05", "Extraction reported possible truncation."))
    if (
        context.name_count != 1
        or context.association_status != "unambiguous"
        or kinds & {"name_conflict", "unclear_mapping"}
    ):
        issues.append(
            registry.issue(
                "QC07",
                f"Name mapping is {context.association_status} "
                f"with {context.name_count} candidate name(s).",
            )
        )
    if context.coverage_risk or "unsupported_content" in kinds:
        issues.append(
            registry.issue("QC08", "Parts of the source were not fully read; check the original.")
        )
    elif "cross_block_join" in kinds:
        issues.append(
            registry.issue(
                "QC08", "The sequence was joined from several blocks; confirm continuity."
            )
        )
    return issues
