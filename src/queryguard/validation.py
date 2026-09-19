"""SQL Validation Service.

Reusable service that parses and validates SQL against an approved schema catalog.
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp
from sqlglot.optimizer.scope import traverse_scope

from queryguard.catalog import SqlCatalogProvider
from queryguard.contracts import (
    GeneratedSql,
    SqlSchemaCatalog,
    SqlValidationError,
    SqlValidationResult,
)


# ── Configuration ────────────────────────────────────────────────────────────────

# System schemas to reject (case-insensitive)
_SYSTEM_SCHEMAS: frozenset[str] = frozenset({
    "pg_catalog",
    "information_schema",
    "pg_toast",
    "pg_temp",
    "pg_internal",
})

# Prohibited function names (case-insensitive)
_PROHIBITED_FUNCTIONS: frozenset[str] = frozenset({
    "pg_sleep",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "dblink_connect",
    "lo_import",
    "lo_export",
    "pg_read_file",
    "pg_read_binary_file",
})


# ── Dialect Mapping ──────────────────────────────────────────────────────────────

def _map_dialect(catalog_dialect: str) -> str | None:
    """Map catalog dialect name to SQLGlot dialect name."""
    mapping = {
        "postgresql": "postgres",
        "postgres": "postgres",
    }
    return mapping.get(catalog_dialect.lower())


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _normalize_identifier(name: str | exp.Expression) -> str:
    """Normalize identifier for case-insensitive comparison."""
    if isinstance(name, exp.Expression):
        name = name.this if hasattr(name, 'this') else str(name)
    return name.lower()


def _is_bind_parameter_column(column: exp.Column) -> bool:
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


def _get_schema_name(node: exp.Expression) -> str | None:
    """Extract schema name from a table expression."""
    if isinstance(node, exp.Table):
        db = node.args.get("db")
        if db is not None:
            return db.this if hasattr(db, 'this') else str(db)
    return None


def _is_system_schema(schema: str | None) -> bool:
    """Check if schema is a system schema."""
    if schema is None:
        return False
    return _normalize_identifier(schema) in _SYSTEM_SCHEMAS


def _is_prohibited_function(func_name: str | None) -> bool:
    """Check if function name is prohibited."""
    if func_name is None:
        return False
    return _normalize_identifier(func_name) in _PROHIBITED_FUNCTIONS


_COLUMN_AMBIGUOUS = "__AMBIGUOUS__"
_COLUMN_MISSING = "__MISSING__"


def _is_scope_source(source_obj: object) -> bool:
    """Return True when the source object is a SQLGlot scope."""
    return hasattr(source_obj, "scope_type")


def _is_cte_source(source_node: exp.Expression, source_obj: object) -> bool:
    """Return True when the selected source is a CTE reference."""
    return _is_scope_source(source_obj) and isinstance(source_node, exp.Table)


def _source_label(source_node: exp.Expression | None, source_obj: object | None) -> str:
    """Human-readable source category for validation messages."""
    if source_node is not None and source_obj is not None and _is_cte_source(source_node, source_obj):
        return "CTE"
    if source_obj is not None and _is_scope_source(source_obj):
        return "derived table"
    return "table"


def _get_visible_sources_in_scope(scope) -> dict[str, tuple[exp.Expression, exp.Table | object]]:
    """Return selected sources visible in the current scope by normalized alias."""
    visible = {}
    for alias, (source_node, source_obj) in scope.selected_sources.items():
        visible[_normalize_identifier(alias)] = (source_node, source_obj)
    return visible


def _collect_physical_tables(scopes: list[object]) -> set[str]:
    """Collect physical tables from scope-selected sources only."""
    physical_tables = set()
    for scope in scopes:
        for _, source_obj in _get_visible_sources_in_scope(scope).values():
            if isinstance(source_obj, exp.Table):
                physical_tables.add(_normalize_identifier(source_obj.name))
    return physical_tables


def _resolve_selected_source_column(
    source_entry: tuple[exp.Expression, exp.Table | object],
    col_name: str,
    catalog: SqlSchemaCatalog,
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> frozenset[str] | str | None:
    """Resolve a column against a selected source."""
    col_lower = _normalize_identifier(col_name)
    _, source_obj = source_entry

    if isinstance(source_obj, exp.Table):
        physical_table = _normalize_identifier(source_obj.name)
        if physical_table not in catalog.allowed_table_names():
            return None
        if col_lower in catalog.allowed_columns(physical_table):
            return frozenset({f"{physical_table}.{col_lower}"})
        return _COLUMN_MISSING

    if not _is_scope_source(source_obj):
        return None

    output_columns = scope_outputs.get(id(source_obj), {})
    if col_lower in output_columns:
        return output_columns[col_lower]
    return _COLUMN_MISSING


def _resolve_qualified_column(
    col_name: str,
    table_qualifier: str,
    catalog: SqlSchemaCatalog,
    visible_sources: dict[str, tuple[exp.Expression, exp.Table | object]],
    outer_scopes: list[object],
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> frozenset[str] | str | None:
    """Resolve a qualified column using current scope and correlated outer scopes."""
    qualifier = _normalize_identifier(table_qualifier)
    source_entry = visible_sources.get(qualifier)
    if source_entry is not None:
        return _resolve_selected_source_column(source_entry, col_name, catalog, scope_outputs)

    for outer_scope in outer_scopes:
        outer_visible = _get_visible_sources_in_scope(outer_scope)
        source_entry = outer_visible.get(qualifier)
        if source_entry is not None:
            return _resolve_selected_source_column(source_entry, col_name, catalog, scope_outputs)

    return None


def _resolve_unqualified_column(
    col_name: str,
    catalog: SqlSchemaCatalog,
    visible_sources: dict[str, tuple[exp.Expression, exp.Table | object]],
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> frozenset[str] | str | None:
    """Resolve an unqualified column within the current scope."""
    col_lower = _normalize_identifier(col_name)
    matches: list[frozenset[str]] = []

    for source_node, source_obj in visible_sources.values():
        if isinstance(source_obj, exp.Table):
            physical_table = _normalize_identifier(source_obj.name)
            if physical_table in catalog.allowed_table_names() and col_lower in catalog.allowed_columns(physical_table):
                matches.append(frozenset({f"{physical_table}.{col_lower}"}))
        elif _is_cte_source(source_node, source_obj):
            output_columns = scope_outputs.get(id(source_obj), {})
            if col_lower in output_columns:
                matches.append(output_columns[col_lower])

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return _COLUMN_AMBIGUOUS
    return None


def _iter_lineage_columns(expression: exp.Expression) -> list[exp.Column]:
    """Return direct column references for a select expression, excluding nested scopes."""
    columns = []
    for column in expression.find_all(exp.Column):
        if column.find_ancestor(exp.Subquery, exp.CTE) is not None:
            continue
        if isinstance(column.this, exp.Star):
            continue
        columns.append(column)
    return columns


def _build_scope_output_columns(
    scope,
    catalog: SqlSchemaCatalog,
    visible_sources: dict[str, tuple[exp.Expression, exp.Table | object]],
    outer_scopes: list[object],
    scope_outputs: dict[int, dict[str, frozenset[str]]],
) -> dict[str, frozenset[str]]:
    """Build output-column metadata with physical lineage for one scope."""
    output_columns: dict[str, frozenset[str]] = {}

    for select_expr in scope.selects:
        output_name = _normalize_identifier(select_expr.alias_or_name)
        if not output_name:
            continue

        physical_columns = set()
        lineage_expression = select_expr.this if isinstance(select_expr, exp.Alias) else select_expr

        for column in _iter_lineage_columns(lineage_expression):
            resolution = _resolve_qualified_column(
                col_name=column.name,
                table_qualifier=column.table,
                catalog=catalog,
                visible_sources=visible_sources,
                outer_scopes=outer_scopes,
                scope_outputs=scope_outputs,
            ) if column.table else _resolve_unqualified_column(
                col_name=column.name,
                catalog=catalog,
                visible_sources=visible_sources,
                scope_outputs=scope_outputs,
            )

            if resolution in (_COLUMN_AMBIGUOUS, _COLUMN_MISSING, None):
                continue
            physical_columns.update(resolution)

        output_columns[output_name] = frozenset(physical_columns)

    return output_columns


# ── Main Validator ───────────────────────────────────────────────────────────────

class SqlValidationService:
    """Service that parses and validates SQL against an approved schema catalog."""

    def __init__(
        self,
        catalog_provider: SqlCatalogProvider,
    ) -> None:
        self._catalog_provider = catalog_provider

    def validate(
        self,
        generated_sql: GeneratedSql | str,
    ) -> SqlValidationResult:
        """Validate SQL against the approved schema catalog.

        Args:
            generated_sql: GeneratedSql object or plain SQL string.

        Returns:
            SqlValidationResult with validation outcome.
        """
        if isinstance(generated_sql, GeneratedSql):
            sql = generated_sql.sql
            model_tables = set(generated_sql.referenced_tables)
            model_columns = set(generated_sql.referenced_columns)
        else:
            sql = generated_sql
            model_tables = set()
            model_columns = set()

        return self._validate_sql(sql, model_tables, model_columns)

    def _validate_sql(
        self,
        sql: str,
        model_tables: set[str],
        model_columns: set[str],
    ) -> SqlValidationResult:
        """Validate SQL string against catalog."""
        catalog = self._catalog_provider.get_catalog()
        dialect = _map_dialect(catalog.dialect)
        if dialect is None:
            return SqlValidationResult(
                valid=False,
                errors=(SqlValidationError(
                    code="UNSUPPORTED_DIALECT",
                    message=f"Unsupported catalog dialect: {catalog.dialect}",
                ),),
            )

        # 1. Empty SQL check
        if not sql or not sql.strip():
            return SqlValidationResult(
                valid=False,
                errors=(SqlValidationError(
                    code="EMPTY_SQL",
                    message="SQL must not be empty",
                ),),
            )

        # 2. Parse SQL
        try:
            ast = sqlglot.parse(sql, read=dialect)
        except sqlglot.ParseError:
            return SqlValidationResult(
                valid=False,
                normalized_sql=None,
                errors=(SqlValidationError(
                    code="PARSE_ERROR",
                    message="SQL could not be parsed",
                ),),
            )

        if len(ast) == 0:
            return SqlValidationResult(
                valid=False,
                errors=(SqlValidationError(
                    code="EMPTY_STATEMENT",
                    message="SQL contains no statements",
                ),),
            )

        if len(ast) > 1:
            return SqlValidationResult(
                valid=False,
                errors=(SqlValidationError(
                    code="MULTIPLE_STATEMENTS",
                    message="Multiple SQL statements are not allowed",
                ),),
            )

        stmt = ast[0]

        # Validate statement structure first (catches non-SELECT/WITH/UNION root types)
        errors = self._validate_statement_root(stmt)
        if errors:
            return SqlValidationResult(
                valid=False,
                normalized_sql=None,
                errors=tuple(errors),
            )

        # Check for forbidden constructs anywhere in AST
        errors.extend(self._check_forbidden_constructs(stmt))

        # Check system schema access
        errors.extend(self._check_system_schema_access(stmt))

        # Check dangerous functions
        errors.extend(self._check_dangerous_functions(stmt))

        # Check wildcards
        errors.extend(self._check_wildcards(stmt))

        if errors:
            return SqlValidationResult(
                valid=False,
                normalized_sql=None,
                errors=tuple(self._deduplicate_errors(errors)),
            )

        # Scope analysis
        scope_errors, parsed_tables, parsed_columns = self._analyze_scopes(stmt, catalog)
        errors.extend(scope_errors)

        # Metadata comparison warnings
        warnings = self._compare_metadata(
            model_tables=model_tables,
            model_columns=model_columns,
            parsed_tables=parsed_tables,
            parsed_columns=parsed_columns,
        )

        # Generate normalized SQL
        normalized_sql = None
        try:
            normalized_sql = sqlglot.transpile(stmt.sql(), read=dialect, write=dialect)[0]
        except Exception:
            normalized_sql = None

        valid = len(errors) == 0

        return SqlValidationResult(
            valid=valid,
            normalized_sql=normalized_sql,
            statement_type=self._get_statement_type(stmt),
            referenced_tables=tuple(sorted(parsed_tables)),
            referenced_columns=tuple(sorted(parsed_columns)),
            errors=tuple(self._deduplicate_errors(errors)),
            warnings=tuple(warnings),
        )

    def _get_statement_type(self, stmt: exp.Expression) -> str | None:
        """Determine the root statement type."""
        if isinstance(stmt, exp.Select):
            return "SELECT"
        elif isinstance(stmt, exp.With):
            # Check what the WITH wraps
            if isinstance(stmt.this, exp.Union):
                return "UNION"
            return "WITH"
        elif isinstance(stmt, exp.Union):
            return "UNION"
        return None

    def _validate_statement_root(self, stmt: exp.Expression) -> list[SqlValidationError]:
        """Validate root statement type is allowed read-only query."""
        errors = []

        # Check root type - return specific error codes for write/DDL/admin operations
        if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete)):
            return [SqlValidationError(
                code="WRITE_OPERATION",
                message=f"Write operation {type(stmt).__name__} is not allowed",
            )]
        elif isinstance(stmt, (exp.Create, exp.Drop)):
            return [SqlValidationError(
                code="DDL_OPERATION",
                message=f"DDL operation {type(stmt).__name__} is not allowed",
            )]
        elif isinstance(stmt, exp.Command):
            # Check for admin commands parsed as Command
            cmd_text = stmt.sql().upper()
            if any(cmd_text.startswith(op) for op in ("COPY", "VACUUM", "ANALYZE", "REINDEX", "CLUSTER")):
                return [SqlValidationError(
                    code="ADMIN_OPERATION",
                    message=f"Administrative command {cmd_text.split()[0]} is not allowed",
                )]
            elif any(cmd_text.startswith(op) for op in ("ALTER", "TRUNCATE")):
                return [SqlValidationError(
                    code="DDL_OPERATION",
                    message=f"DDL operation {cmd_text.split()[0]} is not allowed",
                )]
        elif isinstance(stmt, exp.Alias):
            # VACUUM, REINDEX, CLUSTER parsed as Alias
            if isinstance(stmt.this, exp.Column):
                cmd_name = stmt.this.name.upper()
                if cmd_name in ("VACUUM", "REINDEX", "CLUSTER"):
                    return [SqlValidationError(
                        code="ADMIN_OPERATION",
                        message=f"Administrative command {cmd_name} is not allowed",
                    )]

        # Check allowed root types
        if not isinstance(stmt, (exp.Select, exp.With, exp.Union)):
            return [SqlValidationError(
                code="STATEMENT_NOT_ALLOWED",
                message=f"Statement type {type(stmt).__name__} is not allowed. Only SELECT, WITH, and UNION are allowed.",
            )]

        # For WITH, check the body
        if isinstance(stmt, exp.With):
            body = stmt.this
            if not isinstance(body, (exp.Select, exp.Union)):
                errors.append(SqlValidationError(
                    code="STATEMENT_NOT_ALLOWED",
                    message=f"WITH statement body type {type(body).__name__} is not allowed. Only SELECT and UNION are allowed.",
                ))

        # For UNION, check both sides
        if isinstance(stmt, exp.Union):
            left = stmt.left
            right = stmt.right
            if not isinstance(left, (exp.Select, exp.Union, exp.With)):
                errors.append(SqlValidationError(
                    code="STATEMENT_NOT_ALLOWED",
                    message=f"UNION left branch type {type(left).__name__} is not allowed.",
                ))
            if not isinstance(right, (exp.Select, exp.Union, exp.With)):
                errors.append(SqlValidationError(
                    code="STATEMENT_NOT_ALLOWED",
                    message=f"UNION right branch type {type(right).__name__} is not allowed.",
                ))

        return errors

    def _check_forbidden_constructs(self, stmt: exp.Expression) -> list[SqlValidationError]:
        """Check for forbidden SQL constructs anywhere in AST."""
        errors = []

        # Check for write operations
        for node in stmt.find_all(exp.Insert):
            errors.append(SqlValidationError(
                code="WRITE_OPERATION",
                message="Write operation INSERT is not allowed",
            ))
        for node in stmt.find_all(exp.Update):
            errors.append(SqlValidationError(
                code="WRITE_OPERATION",
                message="Write operation UPDATE is not allowed",
            ))
        for node in stmt.find_all(exp.Delete):
            errors.append(SqlValidationError(
                code="WRITE_OPERATION",
                message="Write operation DELETE is not allowed",
            ))

        # Check for DDL operations
        for node in stmt.find_all(exp.Create):
            errors.append(SqlValidationError(
                code="DDL_OPERATION",
                message="DDL operation CREATE is not allowed",
            ))
        for node in stmt.find_all(exp.Drop):
            errors.append(SqlValidationError(
                code="DDL_OPERATION",
                message="DDL operation DROP is not allowed",
            ))

        # Check for Command nodes (ALTER, TRUNCATE, COPY, etc.)
        for node in stmt.find_all(exp.Command):
            cmd_text = node.sql().upper()
            if any(op in cmd_text for op in ["ALTER", "TRUNCATE", "COPY", "VACUUM", "ANALYZE", "REINDEX", "CLUSTER"]):
                errors.append(SqlValidationError(
                    code="ADMIN_OPERATION" if any(cmd_text.startswith(op) for op in ("COPY", "VACUUM", "ANALYZE", "REINDEX", "CLUSTER")) else "DDL_OPERATION",
                    message=f"Administrative command {cmd_text.split()[0]} is not allowed",
                ))

        # Check for Alias nodes that represent admin commands (VACUUM, REINDEX, CLUSTER)
        for node in stmt.find_all(exp.Alias):
            if isinstance(node.this, exp.Column):
                cmd_name = node.this.name.upper()
                if cmd_name in ("VACUUM", "REINDEX", "CLUSTER"):
                    errors.append(SqlValidationError(
                        code="ADMIN_OPERATION",
                        message=f"Administrative command {cmd_name} is not allowed",
                    ))

        return errors

    def _check_system_schema_access(self, stmt: exp.Expression) -> list[SqlValidationError]:
        """Check for system schema access."""
        errors = []

        for table in stmt.find_all(exp.Table):
            schema = _get_schema_name(table)
            if _is_system_schema(schema):
                errors.append(SqlValidationError(
                    code="SYSTEM_SCHEMA_ACCESS",
                    message=f"Access to system schema '{schema}' is not allowed",
                    context=table.name,
                ))

            # Check if table name itself is a system schema
            if _normalize_identifier(table.name) in _SYSTEM_SCHEMAS:
                errors.append(SqlValidationError(
                    code="SYSTEM_SCHEMA_ACCESS",
                    message=f"Access to system table '{table.name}' is not allowed",
                    context=table.name,
                ))

        return errors

    def _check_dangerous_functions(self, stmt: exp.Expression) -> list[SqlValidationError]:
        """Check for dangerous function calls."""
        errors = []

        for func in stmt.find_all(exp.Func):
            if _is_prohibited_function(func.name):
                errors.append(SqlValidationError(
                    code="DANGEROUS_FUNCTION",
                    message=f"Call to prohibited function '{func.name}' is not allowed",
                    context=func.name,
                ))

        for func in stmt.find_all(exp.Anonymous):
            if _is_prohibited_function(func.this):
                errors.append(SqlValidationError(
                    code="DANGEROUS_FUNCTION",
                    message=f"Call to prohibited function '{func.this}' is not allowed",
                    context=func.this,
                ))

        return errors

    def _check_wildcards(self, stmt: exp.Expression) -> list[SqlValidationError]:
        """Check for wildcard usage (excluding COUNT(*))."""
        errors = []

        for star in stmt.find_all(exp.Star):
            parent = star.parent
            # Allow COUNT(*)
            if isinstance(parent, exp.Count) and isinstance(parent.this, exp.Star):
                continue

            errors.append(SqlValidationError(
                code="WILDCARD_NOT_ALLOWED",
                message="Wildcard selection (*) is not allowed. Use explicit column names. COUNT(*) is permitted.",
            ))

        return errors

    def _analyze_scopes(
        self,
        stmt: exp.Expression,
        catalog: SqlSchemaCatalog,
    ) -> tuple[list[SqlValidationError], set[str], set[str]]:
        """Analyze all query scopes for table and column validation."""
        errors = []
        parsed_tables = set()
        parsed_columns = set()

        try:
            scopes = list(traverse_scope(stmt))
        except Exception as e:
            errors.append(SqlValidationError(
                code="UNSUPPORTED_SQL_FEATURE",
                message=f"Scope analysis failed: {type(e).__name__}",
            ))
            return errors, parsed_tables, parsed_columns

        # First pass: collect all physical tables from scope-aware selected sources
        physical_tables = _collect_physical_tables(scopes)
        for table_name in physical_tables:
            if table_name not in catalog.allowed_table_names():
                errors.append(SqlValidationError(
                    code="TABLE_NOT_ALLOWED",
                    message=f"Table '{table_name}' is not in the approved catalog",
                    context=table_name,
                ))
            else:
                table_def = catalog.get_table(table_name)
                if not table_def.allowed_for_select:
                    errors.append(SqlValidationError(
                        code="TABLE_NOT_ALLOWED",
                        message=f"Table '{table_name}' is not selectable",
                        context=table_name,
                    ))
                else:
                    parsed_tables.add(table_name)

        # Second pass: validate scope-local columns and build output lineage for parent scopes.
        scope_outputs: dict[int, dict[str, frozenset[str]]] = {}
        for scope_idx, scope in enumerate(scopes):
            visible_sources = _get_visible_sources_in_scope(scope)
            outer_scopes = scopes[scope_idx + 1:]

            # Get external columns for this scope (correlated references)
            external_col_names = set()
            for ext_col in getattr(scope, 'external_columns', []):
                external_col_names.add(_normalize_identifier(ext_col.name))

            for col in scope.columns:
                if _is_bind_parameter_column(col):
                    continue
                col_name = _normalize_identifier(col.name)
                table_qualifier = _normalize_identifier(col.table) if col.table else None

                if table_qualifier:
                    resolution = _resolve_qualified_column(
                        col_name=col.name,
                        table_qualifier=table_qualifier,
                        catalog=catalog,
                        visible_sources=visible_sources,
                        outer_scopes=outer_scopes,
                        scope_outputs=scope_outputs,
                    )
                    if resolution == _COLUMN_MISSING:
                        source_entry = visible_sources.get(table_qualifier)
                        if source_entry is None:
                            for outer_scope in outer_scopes:
                                source_entry = _get_visible_sources_in_scope(outer_scope).get(table_qualifier)
                                if source_entry is not None:
                                    break
                        source_node = source_entry[0] if source_entry is not None else None
                        source_obj = source_entry[1] if source_entry is not None else None
                        label = _source_label(source_node, source_obj)
                        errors.append(SqlValidationError(
                            code="COLUMN_NOT_ALLOWED",
                            message=f"Column '{col.name}' not found in {label} '{table_qualifier}'",
                            context=f"{table_qualifier}.{col.name}",
                        ))
                    elif resolution is None:
                        errors.append(SqlValidationError(
                            code="COLUMN_NOT_ALLOWED",
                            message=f"Unknown table reference '{table_qualifier}'",
                            context=f"{table_qualifier}.{col.name}",
                        ))
                    else:
                        parsed_columns.update(resolution)
                else:
                    # Unqualified column
                    # Skip columns that come from subqueries (external_columns) when this scope
                    # has no visible sources that could provide them (e.g., scalar subqueries in SELECT)
                    if col_name in external_col_names and not visible_sources:
                        continue
                    result = _resolve_unqualified_column(
                        col_name=col.name,
                        catalog=catalog,
                        visible_sources=visible_sources,
                        scope_outputs=scope_outputs,
                    )
                    if result == _COLUMN_AMBIGUOUS:
                        errors.append(SqlValidationError(
                            code="UNQUALIFIED_COLUMN_AMBIGUOUS",
                            message=f"Column '{col.name}' is ambiguous across multiple tables",
                            context=col.name,
                        ))
                    elif result is None:
                        errors.append(SqlValidationError(
                            code="COLUMN_NOT_ALLOWED",
                            message=f"Column '{col.name}' not found in any visible table",
                            context=col.name,
                        ))
                    else:
                        parsed_columns.update(result)

            scope_outputs[id(scope)] = _build_scope_output_columns(
                scope=scope,
                catalog=catalog,
                visible_sources=visible_sources,
                outer_scopes=outer_scopes,
                scope_outputs=scope_outputs,
            )

        return errors, parsed_tables, parsed_columns

    def _compare_metadata(
        self,
        model_tables: set[str],
        model_columns: set[str],
        parsed_tables: set[str],
        parsed_columns: set[str],
    ) -> list[str]:
        """Compare model-reported references with parsed references."""
        warnings = []

        if model_tables:
            model_norm = {_normalize_identifier(t) for t in model_tables}
            parsed_norm = {_normalize_identifier(t) for t in parsed_tables}
            if model_norm != parsed_norm:
                warnings.append(
                    "Model-reported tables differ from parsed SQL references."
                )

        if model_columns:
            model_norm = {_normalize_identifier(c) for c in model_columns}
            parsed_norm = {_normalize_identifier(c) for c in parsed_columns}
            if model_norm != parsed_norm:
                warnings.append(
                    "Model-reported columns differ from parsed SQL references."
                )

        return warnings

    def _deduplicate_errors(self, errors: list[SqlValidationError]) -> list[SqlValidationError]:
        """Deduplicate errors by stable key (code, context, line, column)."""
        seen = set()
        unique = []
        for err in errors:
            key = (err.code, err.context, err.line, err.column)
            if key not in seen:
                seen.add(key)
                unique.append(err)
        return unique
