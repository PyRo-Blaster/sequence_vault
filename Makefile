UV ?= uv

.PHONY: setup check scaffold lint typecheck test
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
