PYTHON ?= python3

.PHONY: check
check:
	$(PYTHON) scripts/check_scaffold.py
	git diff --check
