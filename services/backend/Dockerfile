# syntax=docker/dockerfile:1
# Backend image for the API and the worker (same package, different command).
# Build from the repository root: docker build -f services/backend/Dockerfile .
FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
COPY --from=uv /uv /bin/uv
WORKDIR /app

# Locked third-party dependencies first, so source changes reuse this layer.
COPY pyproject.toml uv.lock ./
COPY services/backend/pyproject.toml services/backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-workspace --package sequence-vault

# The package is installed from source in place: settings find config/, the contracts,
# prompts and migrations relative to the repository layout kept under /app.
COPY services/backend/src services/backend/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package sequence-vault
COPY config config
COPY packages/contracts packages/contracts
COPY prompts prompts
COPY database database

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin vault
USER 10001
ENV PATH=/app/.venv/bin:$PATH \
    SEQUENCE_VAULT_ENV=production \
    SEQUENCE_VAULT_API_HOST=0.0.0.0 \
    SEQUENCE_VAULT_API_PORT=8000
EXPOSE 8000
# Worker: python -m sequence_vault.entrypoints.worker_main
# Migrations: python -m sequence_vault.entrypoints.admin migrate
CMD ["python", "-m", "sequence_vault.entrypoints.api_main"]
