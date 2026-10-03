"""Deployment files must agree with the code they configure."""

import json
import re

from sequence_vault.settings import REPO_ROOT

TEMPLATE = REPO_ROOT / "apps/web/nginx/default.conf.template"
COMPOSE = REPO_ROOT / "infrastructure/local/compose.yaml"
SOURCE = REPO_ROOT / "services/backend/src/sequence_vault"


def known_variables() -> set[str]:
    return {
        name
        for path in SOURCE.rglob("*.py")
        for name in re.findall(r"SEQUENCE_VAULT_[A-Z_]+", path.read_text(encoding="utf-8"))
    }


def test_nginx_body_limit_equals_the_upload_policy() -> None:
    policy = json.loads((REPO_ROOT / "config/processing-policy.v1.json").read_text())
    [limit] = re.findall(r"client_max_body_size (\d+);", TEMPLATE.read_text())
    assert int(limit) == policy["limits"]["max_file_bytes"]


def test_nginx_overwrites_the_proxy_secret_and_drops_development_login() -> None:
    text = TEMPLATE.read_text()
    assert 'proxy_set_header X-Proxy-Secret "${SEQUENCE_VAULT_PROXY_SECRET}";' in text
    assert 'proxy_set_header X-Dev-User "";' in text


def test_compose_only_sets_variables_the_backend_reads() -> None:
    configured = set(re.findall(r"^\s+(SEQUENCE_VAULT_[A-Z_]+):", COMPOSE.read_text(), re.M))
    unknown = configured - known_variables() - {"SEQUENCE_VAULT_API_UPSTREAM"}
    assert configured and not unknown


def test_compose_never_enables_development_shortcuts() -> None:
    text = COMPOSE.read_text()
    assert "SEQUENCE_VAULT_ENV: production" in text
    assert "DEV_LOGIN" not in text and "SCANNER: development" not in text
