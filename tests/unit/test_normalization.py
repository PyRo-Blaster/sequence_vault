from hypothesis import given
from hypothesis import strategies as st

from sequence_vault.domain.normalization import normalize


def test_removes_whitespace_including_ideographic_space_and_logs_positions() -> None:
    result = normalize("MK T\n　AY")
    assert result.sequence == "MKTAY"
    assert [(t.operation, t.positions) for t in result.transformations] == [
        ("remove_whitespace", (2, 4, 5))
    ]


def test_uppercases_ascii_only() -> None:
    result = normalize("mkß")
    assert result.sequence == "MKß"
    assert result.transformations[0].operation == "uppercase"
    assert result.transformations[0].positions == (0, 1)


def test_clean_input_has_no_transformations() -> None:
    assert normalize("ACDEFGHIKLMNPQRSTVWY").transformations == ()


@given(st.text(max_size=60))
def test_every_normalized_character_maps_back_to_the_raw_text(raw: str) -> None:
    result = normalize(raw)
    assert len(result.raw_positions) == len(result.sequence)
    for character, position in zip(result.sequence, result.raw_positions, strict=True):
        assert raw[position].upper() == character or raw[position] == character
