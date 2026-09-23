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

### Structural validation internal flow

The structural validator is organized as an internal package under `src/queryguard/validation/`. The public API remains `SqlValidationService` (importable from `queryguard.validation` or `queryguard`).

```text
SqlValidationService
    ↓
parsing.py          — SQLGlot parse invocation, dialect mapping, empty/multi-statement checks
    ↓
statements.py       — Statement-level checks (read-only, write/DDL rejection, wildcards, system schemas, dangerous functions)
    ↓
scopes.py           — SQLGlot scope helpers (alias maps, CTE/derived identification)
    ↓
tables.py           — Physical table resolution and catalog validation
    ↓
columns.py          — Column resolution (qualified/unqualified) and catalog validation
    ↓
lineage.py          — Expression-to-physical-source lineage computation
    ↓
metadata.py         — LLM-reported vs SQLGlot-derived metadata comparison
    ↓
SqlValidationResult
```

These are internal implementation modules. The public API remains `SqlValidationService`.

## Companion layers

QueryGuard-SQLAlchemy is a separate companion package for optional synchronous SQLAlchemy execution of SQL that has already passed QueryGuard validation. Database credentials, execution ownership, read-only grants, and connection configuration remain outside QueryGuard core. This keeps the reusable validation boundary independent from runtime database concerns.
