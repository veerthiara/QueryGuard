"""SQL parsing helpers for QueryGuard structural validation.

Responsibility:
- SQLGlot parse invocation with dialect mapping
- Empty SQL detection
- Multiple-statement rejection
- Parse-error conversion to SqlValidationError

Does NOT own:
- Statement-type validation (see statements.py)
- Table/column resolution (see tables.py, columns.py)
- Scope analysis (see scopes.py)
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp

from queryguard.contracts import SqlValidationError


def map_dialect(catalog_dialect: str) -> str | None:
    """Map catalog dialect name to SQLGlot dialect name."""
    mapping = {
        "postgresql": "postgres",
        "postgres": "postgres",
    }
    return mapping.get(catalog_dialect.lower())


def normalize_identifier(name: str | exp.Expression) -> str:
    """Normalize identifier for case-insensitive comparison."""
    if isinstance(name, exp.Expression):
        name = name.this if hasattr(name, "this") else str(name)
    return name.lower()


def parse_sql(
    sql: str, dialect: str
) -> tuple[list[exp.Expression] | None, SqlValidationError | None]:
    """Parse SQL and check for empty input, parse errors, and multiple statements.

    Returns:
        (statements, error) — exactly one is non-None.
    """
    if not sql or not sql.strip():
        return None, SqlValidationError(
            code="EMPTY_SQL",
            message="SQL must not be empty",
        )

    try:
        ast = sqlglot.parse(sql, read=dialect)
    except sqlglot.ParseError:
        return None, SqlValidationError(
            code="PARSE_ERROR",
            message="SQL could not be parsed",
        )

    if len(ast) == 0:
        return None, SqlValidationError(
            code="EMPTY_STATEMENT",
            message="SQL contains no statements",
        )

    if len(ast) > 1:
        return None, SqlValidationError(
            code="MULTIPLE_STATEMENTS",
            message="Multiple SQL statements are not allowed",
        )

    return ast, None
