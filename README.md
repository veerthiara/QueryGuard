# QueryGuard

QueryGuard is a reusable Python package for safe LLM-assisted SQL analytics. It uses approved schema catalogs, SQLGlot AST parsing, structural validation, and a deliberately layered design that can later add policy validation and safe execution adapters.

## Rev 02 scope

Version 0.2.0 includes:

- schema contracts
- catalog providers
- deterministic schema rendering
- reusable settings
- SQLGlot-based structural validation
- a safe, strict YAML catalog loader

Structural validation permits approved read-only query shapes and checks catalog tables, columns, system schemas, prohibited functions, wildcards, CTEs, derived tables, nested scopes, UNION, and parser-derived physical lineage.

Future revisions will add SQL generation, scope/result policy validation, and execution adapters. Those components are not included yet.

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
