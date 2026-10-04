import pytest
from alembic import command as alembic_command
from sqlalchemy import make_url

from sequence_vault.adapters.persistence import migrate
from sequence_vault.settings import Settings, with_password


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


def test_a_separate_database_password_may_hold_any_character(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose passes the password on its own; URL-special characters stay intact."""
    password = "p@ss:w/rd%#?&"
    url = with_password("postgresql+psycopg://vault@postgres:5432/vault", password)
    parsed = make_url(url)
    assert (parsed.username, parsed.password, parsed.host, parsed.database) == (
        "vault",
        password,
        "postgres",
        "vault",
    )
    assert with_password("postgresql+psycopg://vault:old@h/db", "new") == (
        "postgresql+psycopg://vault:new@h/db"
    )
    with pytest.raises(ValueError):
        with_password("postgresql+psycopg://h/db", password)
    # Alembic's ConfigParser must not interpolate the encoded "%".
    seen: list[str] = []
    monkeypatch.setattr(
        alembic_command,
        "upgrade",
        lambda config, _: seen.append(config.get_main_option("sqlalchemy.url")),
    )
    migrate.upgrade(url)
    assert seen == [url]
