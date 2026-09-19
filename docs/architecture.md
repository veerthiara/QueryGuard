# QueryGuard architecture

QueryGuard separates reusable SQL analytics safeguards from application-specific schema and product code.

```text
Application
    ↓
application YAML/catalog
    ↓
QueryGuard schema catalog
    ↓
SQL generation
    ↓
AST structural validation
    ↓
policy validation
    ↓
approved SQL
    ↓
optional companion execution package
```

## Core boundary

The current core contains catalog contracts and providers, YAML loading, renderer, settings, generation, structural validation, and policy validation. Applications define their own `SqlSchemaCatalog` or catalog provider; QueryGuard never imports application models, database sessions, web frameworks, orchestration code, or database adapters.

The structural validator uses SQLGlot and an approved catalog to reject non-read-only statement shapes, unsupported tables and columns, wildcards (except `COUNT(*)`), system schemas, and dangerous functions. It produces canonical physical-table and physical-column lineage metadata for supported CTEs, derived tables, nested scopes, and UNION queries.

## Companion layers

QueryGuard-SQLAlchemy is a separate companion package for optional synchronous SQLAlchemy execution of SQL that has already passed QueryGuard validation. Database credentials, execution ownership, read-only grants, and connection configuration remain outside QueryGuard core. This keeps the reusable validation boundary independent from runtime database concerns.
