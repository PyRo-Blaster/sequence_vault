# Web application

Chinese TypeScript interface: React, Vite, Ant Design (`zh_CN`), TanStack Query and React Router. The browser talks only to the `/v1` API; it never holds model credentials or database access.

| Folder | Contents |
| --- | --- |
| `src/features/uploads` | Upload panel (formats and limits shown before upload, SHA-256 computed in the browser) and the task list with polling, cancel and reprocess |
| `src/features/review` | Review workspace: source evidence beside candidates, issue localization, resolutions limited to each rule's allowlist, sequence edits with reason and character diff, bulk approval, commit dialog with per-item results |
| `src/features/records` | Search by name, project, length and exact sequence; record detail with versions, provenance and FASTA export |
| `src/features/admin` | The signed-in user's projects and roles |
| `src/components` | Sequence view with residue positions, evidence viewer, character diff, status tags |
| `src/lib` | Generated API types (`pnpm api-types`), API client, code-point/UTF-16 conversion, Chinese labels, session |

API offsets are Unicode code points; `src/lib/codepoints.ts` converts them before any JavaScript string slicing.

## Develop

```sh
make setup                 # backend dependencies (repository root)
make dev                   # PostgreSQL (throwaway unless SEQUENCE_VAULT_DATABASE_URL is set), API and worker on :8000
cd apps/web && pnpm install && pnpm dev   # http://localhost:5173, /v1 proxied to :8000
```

Development sign-in lists the seeded users (`alice@example.test` uploads and reviews, `bob` uploads, `victor` views). Production sign-in goes through the OIDC proxy (ADR 0006).

## Check

```sh
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm e2e    # Playwright journeys against the real backend (starts it with scripts/dev_stack.py)
```

Regenerate `src/lib/api-types.ts` with `pnpm api-types` after the backend OpenAPI changes.
