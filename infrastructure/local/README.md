# Local services

`compose.yaml` runs a production-shaped stack on one machine. Requests flow: browser → **oauth2-proxy** (sign-in, `127.0.0.1:4180`) → **web** (nginx: static app, `/v1` forwarded with the proxy secret) → **api**. The **worker** runs the parsers. The data services are **PostgreSQL 17**, **MinIO** (S3, private versioned bucket) and **ClamAV**. When the API starts, it applies the migrations and creates the bucket; the worker starts once the API is healthy.

The app images come from CI (`ghcr.io/pyro-blaster/sequence-vault/{backend,web}`), so a server only pulls:

```sh
cp infrastructure/local/compose.env.example infrastructure/local/compose.env   # ignored by git; fill in
docker compose -f infrastructure/local/compose.yaml --env-file infrastructure/local/compose.env pull
docker compose -f infrastructure/local/compose.yaml --env-file infrastructure/local/compose.env up -d
docker compose -f infrastructure/local/compose.yaml --env-file infrastructure/local/compose.env \
  exec api python -m sequence_vault.entrypoints.admin add-user --help   # provision users
```

- **Versions.** `SEQUENCE_VAULT_VERSION` in `compose.env` picks the tag: `main` (the default, the latest commit that passed CI) or a full commit SHA. Pin a SHA on shared servers, so a restart never changes the version. `SEQUENCE_VAULT_IMAGES` points at another registry or a fork.
- **Registry access.** GHCR packages are private by default. Either make the two packages public, or run `docker login ghcr.io` on the server once with a token that has `read:packages`.
- **Building from this checkout** (no registry, or local changes): add `-f infrastructure/local/compose.build.yaml` to both commands and `--build` to `up`.
- **Networks.**
  - `data` and `app` are internal, with no internet route. The worker and its parsers are on `data` only.
  - Only oauth2-proxy (which reaches the identity provider) and ClamAV (which downloads signature updates) have egress.
  - PostgreSQL and MinIO are not published. Reach them with `docker compose exec`.
- **Hardening.** Backend and web containers run as non-root, with read-only root filesystems, all capabilities dropped and `no-new-privileges`.
- **Settings.** `SEQUENCE_VAULT_ENV=production` throughout, so development login and the development scanner are refused. The model gateway is off (`SEQUENCE_VAULT_AI_ENABLED=false`).
- **Images.** Third-party tags are pinned; pin digests before a shared deployment. CI builds both app images, validates both Compose files, smoke-tests the images under the same read-only flags, and publishes them only after every job has passed on `main`.

For day-to-day development without containers, `make dev` (backend) and `pnpm dev` (web) are faster.
