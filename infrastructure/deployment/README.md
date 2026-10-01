# Deployment

Two images:

| Image | Build | Runs |
|---|---|---|
| Backend | `docker build -f services/backend/Dockerfile .` (repository root) | API: default command. Worker: `python -m sequence_vault.entrypoints.worker_main`. Migrations: `python -m sequence_vault.entrypoints.admin migrate` |
| Web | `docker build apps/web` | nginx on port 8080: the static app, plus `/v1` forwarded to `SEQUENCE_VAULT_API_UPSTREAM` with `X-Proxy-Secret` |

`infrastructure/local/compose.yaml` is the reference topology; translate it to the target platform. Requirements, all checked by tests or CI where possible:

- **Identity (ADR 0006).**
  - An OIDC proxy in front of the web container sets `X-Forwarded-Email` and must replace any client-sent value.
  - Only the web container knows `SEQUENCE_VAULT_PROXY_SECRET`. The API is reachable only from it.
  - nginx clears `X-Dev-User`.
- **Upload size.** nginx `client_max_body_size` equals the policy's `max_file_bytes` (`tests/unit/test_deployment.py`). A larger value makes over-limit uploads surface as 502.
- **Parser isolation (ADR 0003).**
  - Workers run parsers in a subprocess with resource limits and an empty environment.
  - Containers usually forbid `unshare`. The worker then logs `parser sandbox runs without a network namespace`, and the deployment must give the worker no internet egress: the internal `data` network in Compose, or a NetworkPolicy elsewhere.
  - Enable the model gateway only with an approved egress path to that one endpoint.
- **Health.**
  - The API serves `GET /v1/health`.
  - Workers have no port. Monitor `stage_job` backlog and failure codes instead (see `docs/operations/deployment.md`).
- **Runtime.**
  - Run as non-root with read-only root filesystems; nginx needs writable tmpfs at `/tmp`, `/etc/nginx/conf.d` and `/var/cache/nginx`.
  - Drop all capabilities.
  - Pin image digests when promoting.
- **Smoke test.** `smoke_image.py` runs in CI inside the built backend image. It checks imports, the bundled contracts, policy, prompts and migrations, a non-root user, and a sandboxed parse validated against the DocumentIR schema.

Runbooks: [docs/operations](../../docs/operations/README.md).
