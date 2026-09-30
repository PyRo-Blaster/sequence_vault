# ADR 0001: Monorepo with a modular backend

Status: accepted for the scaffold. Basis: design v1.0, section 3.

Keep one repository with `apps/web`, `services/backend`, shared `packages/contracts`, and independent configuration, infrastructure, and acceptance assets. Run the Python API and processing workers as separate processes from the same package.

This keeps extraction, validation, review, and transactional commit boundaries visible without introducing first-release microservices. Framework and provider choices remain open. Contracts are versioned independently, but internal Python business logic stays in the backend rather than a cross-language shared package.

Consequences: frontend and backend changes can share a contract review; API and workers must respect dependency direction; infrastructure packaging and lockfiles must be added once tooling is chosen. Separate repositories or services require a later ADR with an operational justification.
