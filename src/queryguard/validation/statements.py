"""Statement-level structural checks for QueryGuard.

Responsibility:
- Read-only statement shape validation
- Allowed SELECT/WITH/UNION forms
- Write/DDL rejection
- Dangerous/unsupported statement kinds
- Forbidden constructs anywhere in AST
- System schema access checks
- Dangerous function checks
- Wildcard rules

Does NOT own:
- Table/column resolution (see tables.py, columns.py)
- Scope analysis (see scopes.py)
- Policy enforcement (see queryguard.policy)
"""

from __future__ import annotations

from sqlglot import expressions as exp

from queryguard.contracts import SqlValidationError
from queryguard.validation.parsing import normalize_identifier

# ── Configuration ────────────────────────────────────────────────────────────────

_SYSTEM_SCHEMAS: frozenset[str] = frozenset(
    {
        "pg_catalog",
        "information_schema",
        "pg_toast",
        "pg_temp",
        "pg_internal",
    }
)

_PROHIBITED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "pg_sleep",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "dblink_connect",
        "lo_import",
        "lo_export",
        "pg_read_file",
        "pg_read_binary_file",
    }
)


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _get_schema_name(node: exp.Expression) -> str | None:
    """Extract schema name from a table expression."""
    if isinstance(node, exp.Table):
        db = node.args.get("db")
        if db is not None:
            return db.this if hasattr(db, "this") else str(db)
    return None


def _is_system_schema(schema: str | None) -> bool:
    """Check if schema is a system schema."""
    if schema is None:
        return False
    return normalize_identifier(schema) in _SYSTEM_SCHEMAS


def _is_prohibited_function(func_name: str | None) -> bool:
    """Check if function name is prohibited."""
    if func_name is None:
        return False
    return normalize_identifier(func_name) in _PROHIBITED_FUNCTIONS


# ── Statement Root Validation ────────────────────────────────────────────────────


def validate_statement_root(stmt: exp.Expression) -> list[SqlValidationError]:
    """Validate root statement type is allowed read-only query."""
    errors: list[SqlValidationError] = []

    # Check root type - return specific error codes for write/DDL/admin operations
    if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete)):
        return [
            SqlValidationError(
                code="WRITE_OPERATION",
                message=f"Write operation {type(stmt).__name__} is not allowed",
            )
        ]
    elif isinstance(stmt, (exp.Create, exp.Drop)):
        return [
            SqlValidationError(
                code="DDL_OPERATION",
                message=f"DDL operation {type(stmt).__name__} is not allowed",
            )
        ]
    elif isinstance(stmt, exp.Command):
        cmd_text = stmt.sql().upper()
        if any(
            cmd_text.startswith(op) for op in ("COPY", "VACUUM", "ANALYZE", "REINDEX", "CLUSTER")
        ):
            return [
                SqlValidationError(
                    code="ADMIN_OPERATION",
                    message=f"Administrative command {cmd_text.split()[0]} is not allowed",
                )
            ]
        elif any(cmd_text.startswith(op) for op in ("ALTER", "TRUNCATE")):
            return [
                SqlValidationError(
                    code="DDL_OPERATION",
                    message=f"DDL operation {cmd_text.split()[0]} is not allowed",
                )
            ]
    elif isinstance(stmt, exp.Alias):
        if isinstance(stmt.this, exp.Column):
            cmd_name = stmt.this.name.upper()
            if cmd_name in ("VACUUM", "REINDEX", "CLUSTER"):
                return [
                    SqlValidationError(
                        code="ADMIN_OPERATION",
                        message=f"Administrative command {cmd_name} is not allowed",
                    )
                ]

    # Check allowed root types
    if not isinstance(stmt, (exp.Select, exp.With, exp.Union)):
        return [
            SqlValidationError(
                code="STATEMENT_NOT_ALLOWED",
                message=f"Statement type {type(stmt).__name__} is not allowed. Only SELECT, WITH, and UNION are allowed.",
            )
        ]

    # For WITH, check the body
    if isinstance(stmt, exp.With):
        body = stmt.this
        if not isinstance(body, (exp.Select, exp.Union)):
            errors.append(
                SqlValidationError(
                    code="STATEMENT_NOT_ALLOWED",
                    message=f"WITH statement body type {type(body).__name__} is not allowed. Only SELECT and UNION are allowed.",
                )
            )

    # For UNION, check both sides
    if isinstance(stmt, exp.Union):
        left = stmt.left
        right = stmt.right
        if not isinstance(left, (exp.Select, exp.Union, exp.With)):
            errors.append(
                SqlValidationError(
                    code="STATEMENT_NOT_ALLOWED",
                    message=f"UNION left branch type {type(left).__name__} is not allowed.",
                )
            )
        if not isinstance(right, (exp.Select, exp.Union, exp.With)):
            errors.append(
                SqlValidationError(
                    code="STATEMENT_NOT_ALLOWED",
                    message=f"UNION right branch type {type(right).__name__} is not allowed.",
                )
            )

    return errors


# ── Forbidden Constructs ─────────────────────────────────────────────────────────


def check_forbidden_constructs(stmt: exp.Expression) -> list[SqlValidationError]:
    """Check for forbidden SQL constructs anywhere in AST."""
    errors: list[SqlValidationError] = []

    for _node in stmt.find_all(exp.Insert):
        errors.append(
            SqlValidationError(
                code="WRITE_OPERATION",
                message="Write operation INSERT is not allowed",
            )
        )
    for _node in stmt.find_all(exp.Update):
        errors.append(
            SqlValidationError(
                code="WRITE_OPERATION",
                message="Write operation UPDATE is not allowed",
            )
        )
    for _node in stmt.find_all(exp.Delete):
        errors.append(
            SqlValidationError(
                code="WRITE_OPERATION",
                message="Write operation DELETE is not allowed",
            )
        )

    for _node in stmt.find_all(exp.Create):
        errors.append(
            SqlValidationError(
                code="DDL_OPERATION",
                message="DDL operation CREATE is not allowed",
            )
        )
    for _node in stmt.find_all(exp.Drop):
        errors.append(
            SqlValidationError(
                code="DDL_OPERATION",
                message="DDL operation DROP is not allowed",
            )
        )

    for node in stmt.find_all(exp.Command):
        cmd_text = node.sql().upper()
        if any(
            op in cmd_text
            for op in ["ALTER", "TRUNCATE", "COPY", "VACUUM", "ANALYZE", "REINDEX", "CLUSTER"]
        ):
            errors.append(
                SqlValidationError(
                    code="ADMIN_OPERATION"
                    if any(
                        cmd_text.startswith(op)
                        for op in ("COPY", "VACUUM", "ANALYZE", "REINDEX", "CLUSTER")
                    )
                    else "DDL_OPERATION",
                    message=f"Administrative command {cmd_text.split()[0]} is not allowed",
                )
            )

    for node in stmt.find_all(exp.Alias):
        if isinstance(node.this, exp.Column):
            cmd_name = node.this.name.upper()
            if cmd_name in ("VACUUM", "REINDEX", "CLUSTER"):
                errors.append(
                    SqlValidationError(
                        code="ADMIN_OPERATION",
                        message=f"Administrative command {cmd_name} is not allowed",
                    )
                )

    return errors


# ── System Schema Access ─────────────────────────────────────────────────────────


def check_system_schema_access(stmt: exp.Expression) -> list[SqlValidationError]:
    """Check for system schema access."""
    errors: list[SqlValidationError] = []

    for table in stmt.find_all(exp.Table):
        schema = _get_schema_name(table)
        if _is_system_schema(schema):
            errors.append(
                SqlValidationError(
                    code="SYSTEM_SCHEMA_ACCESS",
                    message=f"Access to system schema '{schema}' is not allowed",
                    context=table.name,
                )
            )

        if normalize_identifier(table.name) in _SYSTEM_SCHEMAS:
            errors.append(
                SqlValidationError(
                    code="SYSTEM_SCHEMA_ACCESS",
                    message=f"Access to system table '{table.name}' is not allowed",
                    context=table.name,
                )
            )

    return errors


# ── Dangerous Functions ──────────────────────────────────────────────────────────


def check_dangerous_functions(stmt: exp.Expression) -> list[SqlValidationError]:
    """Check for dangerous function calls."""
    errors: list[SqlValidationError] = []

    for func in stmt.find_all(exp.Func):
        if _is_prohibited_function(func.name):
            errors.append(
                SqlValidationError(
                    code="DANGEROUS_FUNCTION",
                    message=f"Call to prohibited function '{func.name}' is not allowed",
                    context=func.name,
                )
            )

    for func in stmt.find_all(exp.Anonymous):
        if _is_prohibited_function(func.this):
            errors.append(
                SqlValidationError(
                    code="DANGEROUS_FUNCTION",
                    message=f"Call to prohibited function '{func.this}' is not allowed",
                    context=func.this,
                )
            )

    return errors


# ── Wildcards ────────────────────────────────────────────────────────────────────


def check_wildcards(stmt: exp.Expression) -> list[SqlValidationError]:
    """Check for wildcard usage (excluding COUNT(*))."""
    errors: list[SqlValidationError] = []

    for star in stmt.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Count) and isinstance(parent.this, exp.Star):
            continue

        errors.append(
            SqlValidationError(
                code="WILDCARD_NOT_ALLOWED",
                message="Wildcard selection (*) is not allowed. Use explicit column names. COUNT(*) is permitted.",
            )
        )

    return errors


# ── Statement Type ───────────────────────────────────────────────────────────────


def get_statement_type(stmt: exp.Expression) -> str | None:
    """Determine the root statement type."""
    if isinstance(stmt, exp.Select):
        return "SELECT"
    elif isinstance(stmt, exp.With):
        if isinstance(stmt.this, exp.Union):
            return "UNION"
        return "WITH"
    elif isinstance(stmt, exp.Union):
        return "UNION"
    return None
