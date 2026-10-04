from sequence_vault.domain.qc.characters import describe, scan


def test_standard_residues_raise_nothing() -> None:
    found = scan("ACDEFGHIKLMNPQRSTVWY")
    assert (found.invalid, found.extended, found.ellipsis, found.gaps_and_stops) == ((), (), (), ())


def test_classifies_each_character_family() -> None:
    found = scan("MX1А*-.K...…⋯")
    assert found.extended == (1,)
    assert found.invalid == (2, 3)  # digit and Cyrillic A look-alike
    assert found.gaps_and_stops == (4, 5, 6)  # a single dot is a gap
    assert found.ellipsis == (8, 9, 10, 11, 12)


def test_describe_shows_code_points_for_look_alikes() -> None:
    assert describe("АA", (0,)) == "'А' (U+0410)"
