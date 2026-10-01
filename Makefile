UV ?= uv

.PHONY: setup check scaffold lint typecheck test integration web e2e dev
setup:
	$(UV) sync --locked

check: scaffold lint typecheck test

scaffold:
	$(UV) run --locked python scripts/check_scaffold.py
	git diff --check

lint:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .
	$(UV) run --locked lint-imports

typecheck:
	$(UV) run --locked mypy

test:
	$(UV) run --locked pytest

integration:
	$(UV) run --locked pytest tests/integration tests/security

web:
	cd apps/web && pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test && pnpm build

e2e:
	cd apps/web && pnpm e2e

dev:
	$(UV) run --locked python scripts/dev_stack.py
