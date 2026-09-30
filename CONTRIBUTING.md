# Contributing

Read the design specification and `docs/architecture.md` before implementation. Keep the backend modular; API and workers share one domain and application package. Add infrastructure adapters without coupling business rules to a framework or model provider.

For each phase, implement the corresponding acceptance cases from `docs/roadmap.md`. Add meaningful behavior tests when behavior is introduced. Run `make check` for scaffold changes; add framework-specific checks and lockfiles when choosing implementation dependencies. Commit generated lockfiles and pin parser, model, prompt, schema, and QC versions in persisted runs.

Use Conventional Commits with a scope, for example `chore(scaffold): organize project architecture`. Keep the subject imperative and under 50 characters.

Never commit research originals, production exports, credentials, or identifiable benchmark material. Only synthetic fixtures belong under `tests/fixtures`; private frozen sets remain in controlled storage with versioned manifests. Do not alter the source design document while reorganizing the project; record clarified decisions in an ADR and update the specification deliberately.
