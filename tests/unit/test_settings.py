import pytest

from sequence_vault.settings import Settings


def test_development_shortcuts_are_refused_in_production() -> None:
    for unsafe in (
        {"SEQUENCE_VAULT_SCANNER": "development"},
        {"SEQUENCE_VAULT_DEV_LOGIN": "true"},
        {"SEQUENCE_VAULT_STORAGE": "local"},
    ):
        with pytest.raises(ValueError):
            Settings.from_env(unsafe)


def test_development_allows_local_services_and_ai_stays_off() -> None:
    settings = Settings.from_env(
        {
            "SEQUENCE_VAULT_ENV": "development",
            "SEQUENCE_VAULT_SCANNER": "development",
            "SEQUENCE_VAULT_STORAGE": "local",
            "SEQUENCE_VAULT_DEV_LOGIN": "1",
        }
    )
    assert settings.is_development and settings.dev_login and not settings.ai_enabled
