"""Lineage helpers for QueryGuard structural validation.

Responsibility:
- Mapping expressions/columns back to physical catalog sources
- Projected alias resolution
- CTE output lineage
- Derived-column lineage
- Physical source lineage
- Lineage used to validate outer references

Does NOT own:
- Column resolution (see columns.py)
- Scope traversal (see scopes.py)
- Policy enforcement (see queryguard.policy)
"""

from __future__ import annotations

from sqlglot import expressions as exp

from queryguard.contracts import SqlSchemaCatalog
from queryguard.validation.columns import (
    _COLUMN_AMBIGUOUS,
    _COLUMN_MISSING,
    resolve_qualified_column,
    resolve_unqualified_column,
)
from queryguard.validation.parsing import normalize_identifier


def iter_lineage_columns(expression: exp.Expression) -> list[exp.Column]:
    """Return direct column references for a select expression, excluding nested scopes."""
    columns: list[exp.Column] = []
    for column in expression.find_all(exp.Column):
        if column.find_ancestor(exp.Subquery, exp.CTE) is not None:
            continue
        if isinstance(column.this, exp.Star):
            continue
        columns.append(column)
    return columns


def build_scope_output_columns(
    scope: object,
    catalog: SqlSchemaCatalog,
    visible_sources: dict[str, tuple[exp.Expression, exp.Table | object]],
    outer_scopes: list[object],
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> dict[str, frozenset[str]]:
    """Build output-column metadata with physical lineage for one scope."""
    output_columns: dict[str, frozenset[str]] = {}

    for select_expr in scope.selects:  # type: ignore[attr-defined]
        output_name = normalize_identifier(select_expr.alias_or_name)
        if not output_name:
            continue

        physical_columns: set[str] = set()
        lineage_expression = select_expr.this if isinstance(select_expr, exp.Alias) else select_expr

        for column in iter_lineage_columns(lineage_expression):
            resolution = (
                resolve_qualified_column(
                    col_name=column.name,
                    table_qualifier=column.table,
                    catalog=catalog,
                    visible_sources=visible_sources,
                    outer_scopes=outer_scopes,
                    scope_outputs=scope_outputs,
                )
                if column.table
                else resolve_unqualified_column(
                    col_name=column.name,
                    catalog=catalog,
                    visible_sources=visible_sources,
                    scope_outputs=scope_outputs,
                )
            )

            if resolution in (_COLUMN_AMBIGUOUS, _COLUMN_MISSING, None):
                continue
            if isinstance(resolution, frozenset):
                physical_columns.update(resolution)

        output_columns[output_name] = frozenset(physical_columns)

    return output_columns
