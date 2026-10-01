from sequence_vault.domain.extraction import ExtractedRecord, Name, check_extraction
from sequence_vault.domain.qc.engine import MoleculeType
from sequence_vault.domain.spans import BlockSpan, SequenceSpan

BLOCKS = {"h1": ">RSPO3_C07 heavy chain", "p1": "MKTAYIAKQR"}


def record(names: tuple[Name, ...], spans: tuple[SequenceSpan, ...]) -> ExtractedRecord:
    return ExtractedRecord(names, MoleculeType.PROTEIN, spans, "unambiguous", frozenset())


def test_accepts_name_evidence_inside_a_longer_header() -> None:
    name = Name("RSPO3_C07", "fasta_header", BlockSpan("h1", 1, 10))
    assert check_extraction(BLOCKS, [record((name,), (SequenceSpan("p1", 0, 10, 1),))]) == ()


def test_filename_names_and_pending_content_need_no_evidence() -> None:
    assert check_extraction(BLOCKS, [record((Name("RSPO3", "filename", None),), ())]) == ()


def test_reports_name_that_does_not_match_its_evidence() -> None:
    name = Name("RSPO3_C08", "fasta_header", BlockSpan("h1", 1, 10))
    (problem,) = check_extraction(BLOCKS, [record((name,), ())])
    assert "does not match its evidence" in problem


def test_reports_two_records_claiming_the_same_residues() -> None:
    first = record((), (SequenceSpan("p1", 0, 6, 1),))
    second = record((), (SequenceSpan("p1", 4, 10, 1),))
    (problem,) = check_extraction(BLOCKS, [first, second])
    assert "records 0 and 1 claim overlapping text" in problem
