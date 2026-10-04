import pytest
from hypothesis import given
from hypothesis import strategies as st

from sequence_vault.domain.spans import (
    BlockSpan,
    InvalidSpans,
    SequenceSpan,
    check_spans,
    reconstruct,
    typed_text,
)

BLOCKS = {"p1": "MKTAYIAK", "p2": "QRQISFVK", "cjk": "序列：ACDE"}


def test_reconstructs_spans_in_assembly_order_not_list_order() -> None:
    spans = [SequenceSpan("p2", 0, 3, order=2), SequenceSpan("p1", 0, 4, order=1)]
    assert reconstruct(BLOCKS, spans).text == "MKTAQRQ"


def test_offsets_are_code_points_not_bytes() -> None:
    # "序列：" is three code points but nine UTF-8 bytes.
    assert reconstruct(BLOCKS, [SequenceSpan("cjk", 3, 7, order=1)]).text == "ACDE"


@pytest.mark.parametrize(
    ("spans", "expected"),
    [
        ([], "no sequence spans"),
        ([SequenceSpan("zz", 0, 1, 1)], "unknown block 'zz'"),
        ([SequenceSpan("p1", 3, 3, 1)], "span [3, 3) is outside block 'p1'"),
        ([SequenceSpan("p1", 0, 9, 1)], "span [0, 9) is outside block 'p1'"),
        ([SequenceSpan("p1", 0, 2, 1), SequenceSpan("p2", 0, 2, 3)], "without gaps"),
        ([SequenceSpan("p1", 0, 4, 1), SequenceSpan("p1", 3, 6, 2)], "overlapping spans"),
    ],
)
def test_rejects_unusable_spans(spans: list[SequenceSpan], expected: str) -> None:
    assert any(expected in problem for problem in check_spans(BLOCKS, spans))
    with pytest.raises(InvalidSpans):
        reconstruct(BLOCKS, spans)


def test_maps_text_positions_back_to_merged_block_evidence() -> None:
    rebuilt = reconstruct(BLOCKS, [SequenceSpan("p1", 4, 8, 1), SequenceSpan("p2", 0, 2, 2)])
    assert rebuilt.text == "YIAKQR"
    assert rebuilt.evidence_for([2, 3, 4]) == (BlockSpan("p1", 6, 8), BlockSpan("p2", 0, 1))


def test_typed_text_has_no_evidence() -> None:
    assert typed_text("MKT").evidence_for([0, 1]) == ()


@given(st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=5), st.data())
def test_reconstruction_equals_slices_joined_by_order(
    texts: list[str], data: st.DataObject
) -> None:
    blocks = {f"b{index}": text for index, text in enumerate(texts)}
    spans = []
    for index, text in enumerate(texts):
        start = data.draw(st.integers(0, len(text) - 1))
        end = data.draw(st.integers(start + 1, len(text)))
        spans.append(SequenceSpan(f"b{index}", start, end, order=index + 1))
    rebuilt = reconstruct(blocks, list(reversed(spans)))
    assert rebuilt.text == "".join(blocks[s.block_id][s.start : s.end] for s in spans)
    for position, character in enumerate(rebuilt.text):
        located = rebuilt.locate(position)
        assert located is not None
        assert blocks[located[0]][located[1]] == character
