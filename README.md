# QueryGuard

QueryGuard is a reusable Python package for safely preparing LLM-assisted SQL
analytics. It treats model-produced SQL as untrusted input: approved schema
catalogs constrain what may be queried, structural validation analyzes the SQL
AST, and policy validation enforces user scope and result bounds before SQL can
be considered approved.

QueryGuard does not call an LLM, connect to a database, or execute SQL. An
application supplies its provider adapter and chooses whether an approved query
is passed to a separate execution boundary.

## Architecture

```text
question
  -> provider-neutral generation
  -> structural validation
  -> policy validation
  -> approved SQL
```

The stages stop at the first failure and return a structured result that makes
the rejected stage and errors explicit. Execution is intentionally outside the
core package; `QueryGuard-SQLAlchemy` is an optional companion project for
applications that need a read-only SQLAlchemy execution boundary.

## Requirements and installation

QueryGuard 0.9.0 currently supports Python 3.11.

Install the runtime package:

```bash
python -m pip install .
```

For local development, testing, and package checks:

```bash
python -m pip install -e ".[dev]"
```

The `test` extra installs only pytest and coverage support:

```bash
python -m pip install -e ".[test]"
```

## Quickstart

An application owns its catalog. QueryGuard can load the strict YAML format and
validate supplied SQL without invoking a provider:

```python
from queryguard import (
    StaticSqlCatalogProvider,
    SqlValidationService,
    load_catalog_from_yaml,
)

catalog = load_catalog_from_yaml("catalog.yaml")
validator = SqlValidationService(StaticSqlCatalogProvider(catalog))

result = validator.validate(
    "SELECT id FROM orders WHERE account_id = @user_id LIMIT 20"
)
assert result.valid
```

For the complete application-facing flow, construct `QueryGuard.from_yaml(...)`
with an application-owned provider, then await `guard.prepare(question)`. The
provider returns one strict JSON `GeneratedSql` object; QueryGuard parses and
validates it without retries or execution. See the [facade guide](docs/facade.md)
and [SQL generation guide](docs/sql-generation.md).

## YAML catalogs

Catalogs define approved tables, columns, relationships, aliases, and
user-scope properties. The loader accepts `str` or `pathlib.Path`, uses
`yaml.safe_load`, and rejects unknown keys rather than silently ignoring them.
The included [commerce example](examples/commerce_catalog.yaml) is exercised by
the deterministic E2E acceptance suite. See the [YAML catalog guide](docs/yaml-catalog.md).

## Testing and quality checks

All normal checks are deterministic: they require no API keys, live LLM,
database, or provider SDK.

```bash
make test             # unit and deterministic E2E tests
make test-unit        # tests/queryguard
make test-e2e         # tests/e2e
make lint
make format-check
make typecheck
make coverage
make check            # lint, format, typecheck, and tests
make build
make verify-install   # clean-install built wheel smoke test
```

Equivalent commands use `python -m pytest`, `python -m ruff`, `python -m mypy`,
and `python -m build`. The [testing guide](docs/testing.md) explains why unit
tests, deterministic E2E acceptance tests, and future live-provider quality
evaluations are intentionally separate.

## Documentation

- [Architecture](docs/architecture.md)
- [Facade and pipeline](docs/facade.md)
- [YAML catalog format](docs/yaml-catalog.md)
- [SQL generation protocol](docs/sql-generation.md)
- [Policy validation](docs/policy-validation.md)
- [Testing](docs/testing.md)
- [Release preparation](docs/releasing.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

This repository does not currently include a license. A license choice is
required before public distribution or open-source release.
