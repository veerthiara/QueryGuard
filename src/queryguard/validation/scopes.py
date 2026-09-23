"""Scope-related helpers for QueryGuard structural validation.

Responsibility:
- SQLGlot traverse_scope usage
- selected_sources handling
- Alias maps local to SQLGlot scope
- CTE source identification
- Derived-table source identification
- Physical table vs derived/CTE distinction
- Nested/correlated scope traversal helpers

Does NOT own:
- Policy enforcement (see queryguard.policy)
- Column resolution (see columns.py)
- Physical table collection (see tables.py)
"""

from __future__ import annotations

from sqlglot import expressions as exp

from queryguard.validation.parsing import normalize_identifier


def is_scope_source(source_obj: object) -> bool:
    """Return True when the source object is a SQLGlot scope."""
    return hasattr(source_obj, "scope_type")


def is_cte_source(source_node: exp.Expression, source_obj: object) -> bool:
    """Return True when the selected source is a CTE reference."""
    return is_scope_source(source_obj) and isinstance(source_node, exp.Table)


def source_label(source_node: exp.Expression | None, source_obj: object | None) -> str:
    """Human-readable source category for validation messages."""
    if (
        source_node is not None
        and source_obj is not None
        and is_cte_source(source_node, source_obj)
    ):
        return "CTE"
    if source_obj is not None and is_scope_source(source_obj):
        return "derived table"
    return "table"


def get_visible_sources_in_scope(
    scope: object,
) -> dict[str, tuple[exp.Expression, exp.Table | object]]:
    """Return selected sources visible in the current scope by normalized alias."""
    visible: dict[str, tuple[exp.Expression, exp.Table | object]] = {}
    for alias, (source_node, source_obj) in scope.selected_sources.items():  # type: ignore[attr-defined]
        visible[normalize_identifier(alias)] = (source_node, source_obj)
    return visible


def is_bind_parameter_column(column: exp.Column) -> bool:
    """Return True for executable symbolic parameters, not quoted identifiers."""
    identifier = column.this
    if not isinstance(identifier, exp.Identifier) or identifier.args.get("quoted"):
        return False
    name = column.name
    return (
        (name.startswith("@") and len(name) > 1)
        or name == "?"
        or (name.startswith("$") and name[1:].isdigit())
    )
