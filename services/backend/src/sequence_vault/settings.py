"""Runtime configuration from SEQUENCE_VAULT_* environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[4]


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def with_password(url: str, password: str | None) -> str:
    """Put a raw password into a database URL, percent-encoded, so any character is safe."""
    if password is None:
        return url
    parts = urlsplit(url)
    userinfo, at, host = parts.netloc.rpartition("@")
    if not at or not userinfo:
        raise ValueError("SEQUENCE_VAULT_DATABASE_PASSWORD needs a user in the database URL.")
    user = userinfo.partition(":")[0]
    return urlunsplit(parts._replace(netloc=f"{user}:{quote(password, safe='')}@{host}"))


@dataclass(frozen=True, slots=True)
class Settings:
    env: str
    database_url: str
    storage_backend: str
    local_storage_dir: Path
    s3_endpoint: str | None
    s3_bucket: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    s3_region: str | None
    scanner: str
    clamd_address: str | None
    contracts_dir: Path
    config_dir: Path
    ai_enabled: bool
    ai_provider: str
    ai_model: str
    ai_effort: str
    ai_region: str | None
    ai_project: str | None
    ai_base_url: str | None
    ai_api_key: str | None
    prompts_dir: Path
    trusted_identity_header: str
    proxy_secret: str | None
    dev_login: bool

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        mode = env.get("SEQUENCE_VAULT_ENV", "production")
        settings = cls(
            env=mode,
            database_url=with_password(
                env.get("SEQUENCE_VAULT_DATABASE_URL", ""),
                env.get("SEQUENCE_VAULT_DATABASE_PASSWORD") or None,
            ),
            storage_backend=env.get("SEQUENCE_VAULT_STORAGE", "s3"),
            local_storage_dir=Path(env.get("SEQUENCE_VAULT_LOCAL_STORAGE_DIR", ".local/objects")),
            s3_endpoint=env.get("SEQUENCE_VAULT_OBJECT_STORAGE_ENDPOINT") or None,
            s3_bucket=env.get("SEQUENCE_VAULT_OBJECT_STORAGE_BUCKET") or None,
            s3_access_key=env.get("SEQUENCE_VAULT_OBJECT_STORAGE_ACCESS_KEY") or None,
            s3_secret_key=env.get("SEQUENCE_VAULT_OBJECT_STORAGE_SECRET_KEY") or None,
            s3_region=env.get("SEQUENCE_VAULT_OBJECT_STORAGE_REGION") or None,
            scanner=env.get("SEQUENCE_VAULT_SCANNER", "clamd"),
            clamd_address=env.get("SEQUENCE_VAULT_CLAMD_ADDRESS") or None,
            contracts_dir=Path(
                env.get("SEQUENCE_VAULT_CONTRACTS_DIR", REPO_ROOT / "packages/contracts")
            ),
            config_dir=Path(env.get("SEQUENCE_VAULT_CONFIG_DIR", REPO_ROOT / "config")),
            ai_enabled=_flag(env.get("SEQUENCE_VAULT_AI_ENABLED")),
            ai_provider=env.get("SEQUENCE_VAULT_AI_PROVIDER", "anthropic"),
            ai_model=env.get("SEQUENCE_VAULT_AI_MODEL_VERSION") or "claude-opus-5-5",
            ai_effort=env.get("SEQUENCE_VAULT_AI_EFFORT", "medium"),
            ai_region=env.get("SEQUENCE_VAULT_AI_REGION") or None,
            ai_project=env.get("SEQUENCE_VAULT_AI_PROJECT") or None,
            ai_base_url=env.get("SEQUENCE_VAULT_AI_ENDPOINT") or None,
            ai_api_key=env.get("SEQUENCE_VAULT_AI_API_KEY") or None,
            prompts_dir=Path(
                env.get("SEQUENCE_VAULT_PROMPTS_DIR", REPO_ROOT / "prompts/extraction/v1")
            ),
            trusted_identity_header=env.get("SEQUENCE_VAULT_IDENTITY_HEADER", "X-Forwarded-Email"),
            proxy_secret=env.get("SEQUENCE_VAULT_PROXY_SECRET") or None,
            dev_login=_flag(env.get("SEQUENCE_VAULT_DEV_LOGIN")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Refuse development shortcuts outside development."""
        if not self.is_development:
            if self.scanner != "clamd":
                raise ValueError("Only the ClamAV scanner is allowed outside development.")
            if self.dev_login:
                raise ValueError("Development login is not allowed outside development.")
            if self.storage_backend != "s3":
                raise ValueError("Only S3 storage is allowed outside development.")
