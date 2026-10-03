import pytest

from sequence_vault.domain.naming import name_key


def test_trims_and_case_folds() -> None:
    assert name_key("  RSPO3_C07_v2　") == "rspo3_c07_v2"


def test_rejects_blank_names() -> None:
    with pytest.raises(ValueError, match="blank"):
        name_key(" \t ")
