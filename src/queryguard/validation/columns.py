"""Column resolution and validation for QueryGuard structural validation.

Responsibility:
- Physical column resolution (qualified and unqualified)
- Approved column checking against catalog
- Ambiguous column detection
- Authoritative referenced column metadata

Does NOT own:
- Scope traversal (see scopes.py)
- Physical table collection (see tables.py)
- Lineage computation (see lineage.py)
"""

from __future__ import annotations

from sqlglot import expressions as exp

from queryguard.contracts import SqlSchemaCatalog
from queryguard.validation.parsing import normalize_identifier
from queryguard.validation.scopes import (
    get_visible_sources_in_scope,
    is_cte_source,
    is_scope_source,
)

_COLUMN_AMBIGUOUS = "__AMBIGUOUS__"
_COLUMN_MISSING = "__MISSING__"


def resolve_selected_source_column(
    source_entry: tuple[exp.Expression, exp.Table | object],
    col_name: str,
    catalog: SqlSchemaCatalog,
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> frozenset[str] | str | None:
    """Resolve a column against a selected source."""
    col_lower = normalize_identifier(col_name)
    _, source_obj = source_entry

    if isinstance(source_obj, exp.Table):
        physical_table = normalize_identifier(source_obj.name)
        if physical_table not in catalog.allowed_table_names():
            return None
        if col_lower in catalog.allowed_columns(physical_table):
            return frozenset({f"{physical_table}.{col_lower}"})
        return _COLUMN_MISSING

    if not is_scope_source(source_obj):
        return None

    output_columns = scope_outputs.get(id(source_obj), {})
    if col_lower in output_columns:
        return output_columns[col_lower]
    return _COLUMN_MISSING


def resolve_qualified_column(
    col_name: str,
    table_qualifier: str,
    catalog: SqlSchemaCatalog,
    visible_sources: dict[str, tuple[exp.Expression, exp.Table | object]],
    outer_scopes: list[object],
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> frozenset[str] | str | None:
    """Resolve a qualified column using current scope and correlated outer scopes."""
    qualifier = normalize_identifier(table_qualifier)
    source_entry = visible_sources.get(qualifier)
    if source_entry is not None:
        return resolve_selected_source_column(source_entry, col_name, catalog, scope_outputs)

    for outer_scope in outer_scopes:
        outer_visible = get_visible_sources_in_scope(outer_scope)
        source_entry = outer_visible.get(qualifier)
        if source_entry is not None:
            return resolve_selected_source_column(source_entry, col_name, catalog, scope_outputs)

    return None


def resolve_unqualified_column(
    col_name: str,
    catalog: SqlSchemaCatalog,
    visible_sources: dict[str, tuple[exp.Expression, exp.Table | object]],
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> frozenset[str] | str | None:
    """Resolve an unqualified column within the current scope."""
    col_lower = normalize_identifier(col_name)
    matches: list[frozenset[str]] = []

    for source_node, source_obj in visible_sources.values():
        if isinstance(source_obj, exp.Table):
            physical_table = normalize_identifier(source_obj.name)
            if (
                physical_table in catalog.allowed_table_names()
                and col_lower in catalog.allowed_columns(physical_table)
            ):
                matches.append(frozenset({f"{physical_table}.{col_lower}"}))
        elif is_cte_source(source_node, source_obj):
            output_columns = scope_outputs.get(id(source_obj), {})
            if col_lower in output_columns:
                matches.append(output_columns[col_lower])

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return _COLUMN_AMBIGUOUS
    return None
