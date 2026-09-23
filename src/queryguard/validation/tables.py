"""Physical-table resolution for QueryGuard structural validation.

Responsibility:
- Extracting physical table reads from scope-selected sources
- Canonical table resolution (normalized names)
- Approved catalog table checking
- Excluding CTE aliases/derived names from physical tables
- Authoritative referenced table metadata

Does NOT own:
- Column resolution (see columns.py)
- Scope traversal (see scopes.py)
- Statement-level checks (see statements.py)
"""

from __future__ import annotations

from sqlglot import expressions as exp

from queryguard.contracts import SqlSchemaCatalog, SqlValidationError
from queryguard.validation.parsing import normalize_identifier


def collect_physical_tables(scopes: list[object]) -> set[str]:
    """Collect physical tables from scope-selected sources only."""
    from queryguard.validation.scopes import get_visible_sources_in_scope

    physical_tables: set[str] = set()
    for scope in scopes:
        for _, source_obj in get_visible_sources_in_scope(scope).values():
            if isinstance(source_obj, exp.Table):
                physical_tables.add(normalize_identifier(source_obj.name))
    return physical_tables


def validate_physical_tables(
    physical_tables: set[str],
    catalog: SqlSchemaCatalog,
) -> tuple[set[str], list[SqlValidationError]]:
    """Validate physical tables against the approved catalog.

    Returns:
        (parsed_tables, errors) — parsed_tables contains only approved tables.
    """
    errors: list[SqlValidationError] = []
    parsed_tables: set[str] = set()

    for table_name in physical_tables:
        if table_name not in catalog.allowed_table_names():
            errors.append(
                SqlValidationError(
                    code="TABLE_NOT_ALLOWED",
                    message=f"Table '{table_name}' is not in the approved catalog",
                    context=table_name,
                )
            )
        else:
            table_def = catalog.get_table(table_name)
            if not table_def.allowed_for_select:
                errors.append(
                    SqlValidationError(
                        code="TABLE_NOT_ALLOWED",
                        message=f"Table '{table_name}' is not selectable",
                        context=table_name,
                    )
                )
            else:
                parsed_tables.add(table_name)

    return parsed_tables, errors
