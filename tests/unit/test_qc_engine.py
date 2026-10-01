from sequence_vault.domain.qc.engine import (
    ExtractionContext,
    MoleculeType,
    classify,
    evaluate_spans,
    evaluate_typed,
)
from sequence_vault.domain.qc.registry import Issue, QcRegistry, Severity
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

CLEAN = ExtractionContext(
    name_count=1,
    association_status="unambiguous",
    observation_kinds=frozenset(),
    molecule_type_hint=MoleculeType.PROTEIN,
    coverage_risk=False,
)


def rules(issues: tuple[Issue, ...]) -> list[str]:
    return [issue.rule_id for issue in issues]


def test_clean_protein_has_no_issues(registry: QcRegistry) -> None:
    result = evaluate_spans(
        registry, {"p1": "ACDEFGHIKLMNPQRSTVWY"}, [SequenceSpan("p1", 0, 20, 1)], CLEAN
    )
    assert result.issues == ()
    assert result.molecule_type is MoleculeType.PROTEIN
    assert result.normalized is not None and result.normalized.sequence == "ACDEFGHIKLMNPQRSTVWY"


def test_bad_references_block_with_qc01(registry: QcRegistry) -> None:
    result = evaluate_spans(registry, {"p1": "MKT"}, [SequenceSpan("p1", 0, 9, 1)], CLEAN)
    assert rules(result.issues) == ["QC01"]
    assert result.blocked


def test_issues_point_at_the_offending_source_characters(registry: QcRegistry) -> None:
    blocks = {"p1": "1 MKTAYIAK", "p2": "QRQ...K"}
    spans = [SequenceSpan("p1", 0, 10, 1), SequenceSpan("p2", 0, 7, 2)]
    result = evaluate_spans(registry, blocks, spans, CLEAN)
    by_rule = {issue.rule_id: issue for issue in result.issues}
    assert set(by_rule) == {"QC02", "QC03", "QC05"}
    assert by_rule["QC03"].evidence == (BlockSpan("p1", 0, 1),)
    assert by_rule["QC05"].evidence == (BlockSpan("p2", 3, 6),)
    assert by_rule["QC02"].severity is Severity.INFO
    assert result.blocked


def test_nucleotide_only_sequence_needs_type_confirmation(registry: QcRegistry) -> None:
    result = evaluate_typed(registry, "ACGTACGT", CLEAN)
    assert rules(result.issues) == ["QC11"]
    assert result.molecule_type is MoleculeType.UNCERTAIN


def test_context_raises_mapping_coverage_and_truncation_issues(registry: QcRegistry) -> None:
    context = ExtractionContext(
        name_count=2,
        association_status="conflicting",
        observation_kinds=frozenset({"possible_truncation"}),
        molecule_type_hint=MoleculeType.PROTEIN,
        coverage_risk=True,
    )
    result = evaluate_typed(registry, "MKTAYIAK", context)
    assert rules(result.issues) == ["QC05", "QC07", "QC08"]


def test_declared_fragment_is_not_blocked_by_a_truncation_report(registry: QcRegistry) -> None:
    context = ExtractionContext(
        name_count=1,
        association_status="unambiguous",
        observation_kinds=frozenset({"possible_truncation"}),
        molecule_type_hint=MoleculeType.PROTEIN,
        coverage_risk=False,
        declared_fragment=True,
    )
    assert evaluate_typed(registry, "MKTAYIAK", context).issues == ()


def test_classify_needs_letter_evidence_and_agreement() -> None:
    assert classify("MKTAYIAK", MoleculeType.PROTEIN, frozenset()) is MoleculeType.PROTEIN
    assert classify("ACGTN", MoleculeType.PROTEIN, frozenset()) is MoleculeType.UNCERTAIN
    assert classify("MKTAYIAK", MoleculeType.NUCLEIC_ACID, frozenset()) is MoleculeType.UNCERTAIN
    assert (
        classify("MKTAYIAK", MoleculeType.PROTEIN, frozenset({"possible_nucleic_acid"}))
        is MoleculeType.UNCERTAIN
    )
