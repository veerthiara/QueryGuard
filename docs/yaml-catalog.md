# YAML catalogs

QueryGuard loads application-owned YAML catalogs through `load_catalog_from_yaml(path)` or `parse_catalog_yaml(content)`. File I/O and parsing are separate so applications can decide where their configuration text comes from.

The loader uses `yaml.safe_load`; Python object tags and other unsafe constructors are not accepted. Every YAML level is strict: unknown keys are rejected to make misspellings visible.

## Canonical schema

```yaml
catalog:
  name: commerce
  version: "1"
  dialect: postgresql # optional; defaults to postgresql

tables:
  - name: customers
    description: Customer accounts
    aliases: [customer_accounts]
    columns:
      - name: id
        description: Customer identifier
        type: uuid
        primary_key: true

  - name: orders
    description: Customer orders
    user_scoped: true
    scope_strategy: direct
    scope_description: Restricted by account
    business_rules:
      - Totals are stored in cents.
    columns:
      - name: id
        description: Order identifier
        type: uuid
        primary_key: true
      - name: account_id
        description: Owning account
        type: uuid
        user_scope: true
      - name: customer_id
        description: Customer reference
        type: uuid
        foreign_key: true
        foreign_key_target: customers.id

relationships:
  - left_table: orders
    left_column: customer_id
    right_table: customers
    right_column: id
    relationship_type: many_to_one
    description: An order belongs to one customer.

global_rules:
  - Only approved columns may be queried.
```

At the top level, `catalog` and `tables` are required; `relationships` and `global_rules` are optional. In `catalog`, `name` and `version` are required, while `dialect` defaults to `postgresql` through the existing contract.

Each table requires `name`, `description`, and `columns`. Optional table keys are `user_scoped`, `allowed_for_select`, `aliases`, `business_rules`, `scope_strategy`, and `scope_description`. Their defaults come from `SqlTableDefinition`.

Each column requires `name`, `description`, and `type`. Friendly YAML keys map to contract keys: `type` becomes `data_type`, `primary_key` becomes `is_primary_key`, `foreign_key` becomes `is_foreign_key`, and `user_scope` becomes `is_user_scope`. Optional column flags use the defaults from `SqlColumnDefinition`.

Each relationship requires `left_table`, `left_column`, `right_table`, `right_column`, and `relationship_type`; `description` is optional. Relationship types are `one_to_one`, `one_to_many`, `many_to_one`, and `many_to_many`.

When `foreign_key: true`, `foreign_key_target` is required. A direct `user_scoped: true` table must have at least one `user_scope: true` column. Relationships must reference approved tables and columns, and duplicate tables, columns, and relationships are rejected by the schema contract.

Malformed YAML, missing required sections, invalid structure or field values, unknown keys, and contract validation failures raise `CatalogYamlError`. The original parsing or validation error is retained as the exception cause where useful.
