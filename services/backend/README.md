# Modular Python backend

`src/sequence_vault` is the shared package for the API and processing workers. `domain` holds the tested, framework-free core: span reconstruction, normalization, QC rules, candidate and task lifecycles, and publication decisions. No server, persistence, queue or parser is implemented yet.

Select the Python framework, build/dependency tooling, queue, ORM, and lockfile during implementation. Register API and worker entry points separately. Wire adapters at these composition roots. Avoid importing concrete infrastructure into domain code.

The commit service is an application use case with database transaction boundaries; it is not an AI tool. Model gateway credentials must not grant access to published data. Every parser must implement format/security/coverage contracts before being enabled in the registry.
