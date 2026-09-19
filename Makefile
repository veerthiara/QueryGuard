PYTHON ?= python

.PHONY: test test-unit test-e2e lint format-check typecheck coverage build verify-install check eval eval-safety

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest tests/queryguard

test-e2e:
	$(PYTHON) -m pytest tests/e2e

lint:
	$(PYTHON) -m ruff check src tests evals

format-check:
	$(PYTHON) -m ruff format --check src tests evals

typecheck:
	$(PYTHON) -m mypy src/queryguard evals/queryguard_evals

coverage:
	$(PYTHON) -m pytest --cov=queryguard --cov-report=term-missing

build:
	rm -rf build dist
	$(PYTHON) -m build

verify-install:
	$(PYTHON) scripts/verify_package.py

eval:
	$(PYTHON) evals/run_eval.py --model "$(MODEL)"

eval-safety:
	$(PYTHON) evals/run_eval.py --model "$(MODEL)" --safety-only

check: lint format-check typecheck test
