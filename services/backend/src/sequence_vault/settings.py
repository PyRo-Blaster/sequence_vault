"""Runtime configuration from SEQUENCE_VAULT_* environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


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
            database_url=env.get("SEQUENCE_VAULT_DATABASE_URL", ""),
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
