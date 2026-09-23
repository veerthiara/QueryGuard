# Contributing to QueryGuard

QueryGuard is a Python 3.11 package. Its deterministic local checks require no
API keys, LLM provider, database, or network service beyond installing Python
dependencies.

## Set up a development checkout

```bash
git clone <repository-url>
cd QueryGuard
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Use `Scripts\\activate` instead of `bin/activate` on Windows.

## Run checks

```bash
# Focused unit and deterministic end-to-end suites
python -m pytest tests/queryguard
python -m pytest tests/e2e

# Full regression suite
python -m pytest

# Quality gates
python -m ruff check src tests evals
python -m ruff format --check src tests evals
python -m mypy src/queryguard evals/queryguard_evals
python -m pytest --cov=queryguard --cov-report=term-missing

# Package and wheel verification
python -m build
python scripts/verify_package.py

# Convenience targets
make check
make build
```

Mypy intentionally checks production source under `src/queryguard`; test
helpers are covered by pytest and Ruff rather than making test scaffolding part
of the package typing contract.

## Where tests belong

- `tests/queryguard/` contains focused unit and module-level regression tests.
- `tests/e2e/` contains deterministic full-pipeline acceptance tests using the
  real example YAML and test-only providers.
- Optional live-provider quality evaluations belong in `evals/`, outside the
  normal test suite. They answer a different question and must not make local
  or CI tests depend on model availability or network services.

A unit test asks, “Does this function or module behave correctly?” An E2E
acceptance test asks, “Do QueryGuard modules work together correctly?” A live
evaluation asks, “Does a real LLM generate useful SQL?”

## Add an evaluation regression case

Live evaluations are opt-in tooling under `evals/`, never normal pytest or CI.
Add a YAML case to `evals/cases/commerce.yaml` when a real model exposes a
repeatable semantic gap worth tracking. Use property expectations rather than
exact SQL, classify unsafe or unsupported requests as `kind: rejection`, and
add deterministic harness tests if scoring behavior changes. Run it locally
with `make eval MODEL=<local-ollama-model>` or the rejection subset with
`make eval-safety MODEL=<local-ollama-model>`.

## Make changes safely

Every behavioral change must add or update tests. For a bug fix:

1. Add a failing regression test that reproduces the bug.
2. Implement the smallest appropriate fix.
3. Run the relevant unit tests and deterministic E2E suite.
4. Run the quality checks before opening a pull request.

When adding YAML catalog behavior, add strict loader tests and update the YAML
catalog guide. When changing structural validation, add focused validation
tests. When changing user scope or result bounds, add focused policy tests.
When changing generation-to-approval flow, add facade tests and an E2E scenario
when the behavior crosses stage boundaries.

### If modifying structural validation

Structural validation lives in `src/queryguard/validation/` as an internal package:

- **parsing behavior** → `validation/parsing.py`
- **statement form rules** → `validation/statements.py`
- **physical tables** → `validation/tables.py`
- **columns** → `validation/columns.py`
- **scope/alias resolution** → `validation/scopes.py`
- **derived/CTE lineage** → `validation/lineage.py`
- **generated-vs-derived metadata** → `validation/metadata.py`
- **orchestration** → `validation/service.py`

Every structural validation bug fix must include:
- positive test if relevant
- negative regression test
- E2E verification where relevant

Safety-sensitive changes need negative tests as well as happy-path tests. Cover
cases such as forbidden tables or columns, missing user scope, literal user
scope, unsafe `OR`, unbounded results, and UNION edge cases. A SQLGlot-related
change is incomplete if it only proves valid SQL still works.

## Build and release preparation

Build artifacts are generated locally and are not committed. See
[docs/releasing.md](docs/releasing.md) for the future release checklist. This
repository has no license file yet; a license decision is required before any
public release.
