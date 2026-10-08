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


def test_nginx_sets_every_header_once_at_server_level() -> None:
    """A location with its own add_header silently drops the server's headers (B12)."""
    text = TEMPLATE.read_text()
    locations = re.findall(r"^    location [^{]+\{(.*?)^    \}", text, re.M | re.S)
    assert len(locations) == 3
    assert not any("add_header" in body or "expires" in body for body in locations)
    headers = re.findall(r"^    add_header ([\w-]+) ", text, re.M)
    assert sorted(headers) == sorted(set(headers))
    assert {"Content-Security-Policy", "X-Frame-Options", "Cache-Control"} <= set(headers)


def test_compose_only_sets_variables_the_backend_reads() -> None:
    configured = set(re.findall(r"^\s+(SEQUENCE_VAULT_[A-Z_]+):", COMPOSE.read_text(), re.M))
    unknown = configured - known_variables() - {"SEQUENCE_VAULT_API_UPSTREAM"}
    assert configured and not unknown


def test_compose_never_enables_development_shortcuts() -> None:
    text = COMPOSE.read_text()
    assert "SEQUENCE_VAULT_ENV: production" in text
    assert "DEV_LOGIN" not in text and "SCANNER: development" not in text


def services(text: str) -> dict[str, str]:
    """Top-level Compose services and their bodies (two-space keys under `services:`)."""
    body = text.split("\nservices:\n", 1)[1].split("\nnetworks:", 1)[0]
    parts = re.split(r"^  ([a-z0-9-]+):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_servers_pull_images_and_the_api_replaces_the_one_shot_jobs() -> None:
    """compose.yaml builds nothing; the API migrates and creates the bucket at start-up."""
    text = COMPOSE.read_text()
    assert "build:" not in text
    found = services(text)
    assert "migrate" not in found and "minio-bucket" not in found
    assert 'SEQUENCE_VAULT_MIGRATE_ON_START: "true"' in found["api"]
    assert 'SEQUENCE_VAULT_OBJECT_STORAGE_CREATE_BUCKET: "true"' in found["api"]
    assert "api: {condition: service_healthy}" in found["worker"]
    # Every service running an app image can be built from source with the override.
    app = {
        n for n, body in found.items() if "<<: *backend" in body or "SEQUENCE_VAULT_IMAGES" in body
    }
    assert app == {"api", "worker", "web"}
    assert text.count("${SEQUENCE_VAULT_IMAGES:-ghcr.io/pyro-blaster/sequence-vault}/") == 2
    build = services((COMPOSE.parent / "compose.build.yaml").read_text() + "\nnetworks:")
    assert set(build) == app
