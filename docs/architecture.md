# QueryGuard architecture

QueryGuard separates reusable SQL analytics safeguards from application-specific schema and product code.

```text
Application
    ↓
application YAML/catalog
    ↓
QueryGuard schema catalog
    ↓
SQL generation (future optional integration)
    ↓
AST structural validation
    ↓
policy validation (future optional integration)
    ↓
read-only execution adapter (future optional integration)
```

## Rev 01 core

The current core contains contracts, catalog providers, renderer, settings, and structural validation. Applications define their own `SqlSchemaCatalog` or catalog provider; QueryGuard never imports application models, database sessions, web frameworks, or orchestration code.

The structural validator uses SQLGlot and an approved catalog to reject non-read-only statement shapes, unsupported tables and columns, wildcards (except `COUNT(*)`), system schemas, and dangerous functions. It produces canonical physical-table and physical-column lineage metadata for supported CTEs, derived tables, nested scopes, and UNION queries.

## Future optional layers

Generation adapters can create SQL candidates from application questions. Policy validation can require user scope and result bounds. Read-only execution adapters can bind parameters and apply database-level protections. These layers are intentionally separate because AST validation alone is not a database security boundary.

Application schemas, account identity rules, database credentials, execution ownership, and product-specific prompt behavior stay outside QueryGuard. This lets the same core serve multiple applications without coupling their domains.
