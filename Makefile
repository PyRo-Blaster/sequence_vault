PYTHON ?= python3

.PHONY: check-deps check
check-deps:
	$(PYTHON) -m pip install --require-virtualenv -r scripts/requirements.txt

check:
	$(PYTHON) scripts/check_scaffold.py
	git diff --check
