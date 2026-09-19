# QueryGuard

QueryGuard is a reusable Python package for safe LLM-assisted SQL analytics. It uses approved schema catalogs, SQLGlot AST parsing, structural validation, and a deliberately layered design that can later add policy validation and safe execution adapters.

## Rev 07 scope

Version 0.7.0 includes:

- schema contracts
- catalog providers
- deterministic schema rendering
- reusable settings
- SQLGlot-based structural validation
- a safe, strict YAML catalog loader
- provider-neutral, single-pass SQL generation
- policy validation for user scope and result bounds
- a unified preparation facade

Structural validation permits approved read-only query shapes and checks catalog tables, columns, system schemas, prohibited functions, wildcards, CTEs, derived tables, nested scopes, UNION, and parser-derived physical lineage.

Generation uses an application-supplied provider interface and returns the existing `GeneratedSql` contract. Policy validation enforces direct user scope and result bounds without executing SQL.

QueryGuard ends with approved SQL after structural and policy validation. Database execution is intentionally outside the core package.

## Unified preparation facade

The simplest application-facing path is the `QueryGuard` facade. It generates SQL, structurally validates it, applies policy validation, and never executes SQL.

```python
from queryguard import QueryGuard

guard = QueryGuard.from_yaml(
    "catalog.yaml",
    provider=my_provider,
)

result = await guard.prepare(
    "How many orders were placed this month?"
)

if result.approved:
    sql = result.generated.sql
else:
    print(result.errors)
```

For SQL supplied by another agent or tool, use `guard.validate_sql(sql)` to run structural and policy validation without an LLM call. If SQL is approved, an agent can choose a separate execution tool or the `queryguard-sqlalchemy` companion package.

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

## Policy validation

Policy validation is a separate stage after structural validation. It requires direct user-scope predicates for configured user-scoped tables and bounds row-returning results.

```python
from queryguard import (
    SqlPolicyValidationService,
    StaticSqlCatalogProvider,
    load_catalog_from_yaml,
)

catalog = load_catalog_from_yaml("catalog.yaml")
provider = StaticSqlCatalogProvider(catalog)
policy = SqlPolicyValidationService(provider)

result = policy.validate(
    "SELECT id FROM orders "
    "WHERE account_id = @user_id "
    "LIMIT 100"
)

assert result.valid
```

See [the policy validation guide](docs/policy-validation.md) for the supported parameter forms, scope semantics, and LIMIT rules.

## Execution is a companion concern

QueryGuard's pipeline ends after policy validation:

```text
question -> generation -> structural validation -> policy validation -> approved SQL
```

For optional synchronous SQLAlchemy execution of approved SQL, install and use the separate `queryguard-sqlalchemy` companion package. It owns parameter binding, read-only transaction setup, timeouts, bounded fetches, and database-specific behavior. QueryGuard core does not create connections, execute SQL, or depend on SQLAlchemy.
