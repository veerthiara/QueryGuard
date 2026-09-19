# QueryGuard

QueryGuard is a reusable Python package for safe LLM-assisted SQL analytics. It uses approved schema catalogs, SQLGlot AST parsing, structural validation, and a deliberately layered design that can later add policy validation and safe execution adapters.

## Rev 03 scope

Version 0.3.0 includes:

- schema contracts
- catalog providers
- deterministic schema rendering
- reusable settings
- SQLGlot-based structural validation
- a safe, strict YAML catalog loader
- provider-neutral, single-pass SQL generation

Structural validation permits approved read-only query shapes and checks catalog tables, columns, system schemas, prohibited functions, wildcards, CTEs, derived tables, nested scopes, UNION, and parser-derived physical lineage.

Generation uses an application-supplied provider interface and returns the existing `GeneratedSql` contract. It does not validate or execute generated SQL.

Future revisions will add scope/result policy validation and execution adapters. Those components are not included yet.

## Install and test

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

## Programmatic catalog and validation

```python
from queryguard import (
    SqlColumnDefinition,
    SqlSchemaCatalog,
    SqlTableDefinition,
    SqlValidationService,
    StaticSqlCatalogProvider,
)

catalog = SqlSchemaCatalog(
    catalog_name="commerce",
    catalog_version="1.0",
    tables=(
        SqlTableDefinition(
            name="orders",
            description="Customer orders",
            user_scoped=True,
            columns=(
                SqlColumnDefinition(
                    name="id",
                    description="Order identifier",
                    data_type="uuid",
                    is_primary_key=True,
                ),
                SqlColumnDefinition(
                    name="account_id",
                    description="Owning account",
                    data_type="uuid",
                    is_user_scope=True,
                ),
            ),
        ),
    ),
)

validator = SqlValidationService(StaticSqlCatalogProvider(catalog))
result = validator.validate("SELECT id FROM orders")
assert result.valid
```

## Using an application-owned YAML catalog

Keep the catalog in the consuming application, then load it into QueryGuard:

```python
from queryguard import (
    StaticSqlCatalogProvider,
    SqlValidationService,
    load_catalog_from_yaml,
)

catalog = load_catalog_from_yaml("catalog.yaml")
provider = StaticSqlCatalogProvider(catalog)
validator = SqlValidationService(provider)
```

The loader accepts `str` and `pathlib.Path` paths and uses `yaml.safe_load`. YAML keys are strict: unknown keys are rejected instead of ignored. See [the YAML catalog guide](docs/yaml-catalog.md) for the canonical format.

## Provider-neutral SQL generation

The consuming application implements the provider adapter; QueryGuard does not depend on any provider SDK.

```python
from queryguard import (
    SqlGenerationService,
    StaticSqlCatalogProvider,
    load_catalog_from_yaml,
)

catalog = load_catalog_from_yaml("catalog.yaml")
catalog_provider = StaticSqlCatalogProvider(catalog)
provider = MyApplicationProvider(...)

generator = SqlGenerationService(
    catalog_provider=catalog_provider,
    provider=provider,
)

generated = await generator.generate(
    "How many orders were placed this month?"
)

print(generated.sql)
```

Providers return exactly one JSON object matching `GeneratedSql`; Markdown and surrounding prose are rejected. See [the SQL generation guide](docs/sql-generation.md) for the provider protocol and stage boundaries.
