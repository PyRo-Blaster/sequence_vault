import pytest
from moto import mock_aws
from sqlalchemy import make_url

from sequence_vault.adapters.storage.s3 import S3ObjectStore
from sequence_vault.entrypoints import bootstrap
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


def test_a_separate_database_password_may_hold_any_character() -> None:
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


def test_start_up_steps_run_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API replaces the one-shot migrate and bucket jobs when both settings are on."""
    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "upgrade", lambda url: calls.append(url))
    base = {"SEQUENCE_VAULT_DATABASE_URL": "postgresql+psycopg://u@h/db"}
    with mock_aws():
        store = S3ObjectStore("vault", access_key="test", secret_key="test")
        bootstrap.prepare(Settings.from_env(base), store)
        assert calls == [] and store.ensure_bucket() is True  # nothing was created before
        store.client.delete_bucket(Bucket="vault")
        enabled = {
            **base,
            "SEQUENCE_VAULT_MIGRATE_ON_START": "true",
            "SEQUENCE_VAULT_OBJECT_STORAGE_CREATE_BUCKET": "true",
        }
        bootstrap.prepare(Settings.from_env(enabled), store)
        assert calls == ["postgresql+psycopg://u@h/db"]
        assert store.ensure_bucket() is False
