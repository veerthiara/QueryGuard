PYTHON ?= python

.PHONY: test test-unit test-e2e lint format-check typecheck coverage build verify-install check

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest tests/queryguard

test-e2e:
	$(PYTHON) -m pytest tests/e2e

lint:
	$(PYTHON) -m ruff check src tests

format-check:
	$(PYTHON) -m ruff format --check src tests

typecheck:
	$(PYTHON) -m mypy src/queryguard

coverage:
	$(PYTHON) -m pytest --cov=queryguard --cov-report=term-missing

build:
	$(PYTHON) -m build

verify-install:
	$(PYTHON) scripts/verify_package.py

check: lint format-check typecheck test
