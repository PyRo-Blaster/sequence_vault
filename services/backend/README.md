# Modular Python backend

`src/sequence_vault` is the shared package for the API and processing workers. Module markers reserve boundaries; no server, persistence, processing, or publication behavior is implemented.

Select the Python framework, build/dependency tooling, queue, ORM, and lockfile during implementation. Register API and worker entry points separately. Wire adapters at these composition roots. Avoid importing concrete infrastructure into domain code.

The commit service is an application use case with database transaction boundaries; it is not an AI tool. Model gateway credentials must not grant access to published data. Every parser must implement format/security/coverage contracts before being enabled in the registry.
