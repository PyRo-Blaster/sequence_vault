import pytest

from sequence_vault.domain.qc.registry import QcRegistry, Severity


def test_loads_the_v1_registry(registry: QcRegistry) -> None:
    assert registry.version == "1.0"
    assert set(registry.rules) == {f"QC{number:02}" for number in range(1, 12)}
    assert registry.rules["QC05"].severity is Severity.BLOCK
    assert "register_fragment" in registry.rules["QC05"].allowed_resolutions


def test_issue_severity_always_comes_from_the_registry(registry: QcRegistry) -> None:
    assert registry.issue("QC04", "extended residue").severity is Severity.REVIEW


def test_refuses_a_registry_that_allows_generic_block_overrides() -> None:
    with pytest.raises(ValueError, match="generic override"):
        QcRegistry.from_dict(
            {"qc_version": "x", "generic_block_override_allowed": True, "rules": []}
        )


def test_refuses_rules_without_resolutions() -> None:
    data = {
        "qc_version": "x",
        "generic_block_override_allowed": False,
        "rules": [{"rule_id": "QC01", "severity": "BLOCK", "allowed_resolutions": []}],
    }
    with pytest.raises(ValueError, match="no resolutions"):
        QcRegistry.from_dict(data)
