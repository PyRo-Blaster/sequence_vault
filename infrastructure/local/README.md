# Local services

`compose.yaml` runs a production-shaped stack on one machine. Requests flow: browser → **oauth2-proxy** (sign-in, `127.0.0.1:4180`) → **web** (nginx: static app, `/v1` forwarded with the proxy secret) → **api**. The **worker** runs the parsers. The data services are **PostgreSQL 17**, **MinIO** (S3, private versioned bucket) and **ClamAV**. A one-shot **migrate** service applies the migrations before the API and worker start.

```sh
cp infrastructure/local/compose.env.example infrastructure/local/compose.env   # ignored by git; fill in
docker compose -f infrastructure/local/compose.yaml --env-file infrastructure/local/compose.env up --build
docker compose -f infrastructure/local/compose.yaml --env-file infrastructure/local/compose.env \
  exec api python -m sequence_vault.entrypoints.admin add-user --help   # provision users
```

- **Networks.**
  - `data` and `app` are internal, with no internet route. The worker and its parsers are on `data` only.
  - Only oauth2-proxy (which reaches the identity provider) and ClamAV (which downloads signature updates) have egress.
  - PostgreSQL and MinIO are not published. Reach them with `docker compose exec`.
- **Hardening.** Backend and web containers run as non-root, with read-only root filesystems, all capabilities dropped and `no-new-privileges`.
- **Settings.** `SEQUENCE_VAULT_ENV=production` throughout, so development login and the development scanner are refused. The model gateway is off (`SEQUENCE_VAULT_AI_ENABLED=false`).
- **Images.** Tags are pinned; pin digests before a shared deployment. CI builds both images, validates this file, and smoke-tests the images under the same read-only flags.

For day-to-day development without containers, `make dev` (backend) and `pnpm dev` (web) are faster.
