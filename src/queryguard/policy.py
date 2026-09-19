"""Generic SQL user-scope and result-bound policy validation."""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from queryguard.catalog import SqlCatalogProvider
from queryguard.contracts import SqlPolicyError, SqlPolicyValidationResult, SqlSchemaCatalog
from queryguard.settings import SqlAnalyticsSettings


def _map_dialect(catalog_dialect: str) -> str | None:
    """Map a catalog dialect to the SQLGlot dialect name."""

    return {"postgresql": "postgres", "postgres": "postgres"}.get(catalog_dialect.lower())


def _extract_bound_parameters(stmt: exp.Expression) -> tuple[str, ...]:
    """Extract supported bind parameters from SQLGlot AST nodes, never literals."""

    parameters: set[str] = set()
    for column in stmt.find_all(exp.Column):
        name = column.name
        if not name:
            continue
        if name.startswith("$") and name[1:].isdigit():
            parameters.add(name[1:])
        elif name == "?":
            parameters.add("?")
        elif name.startswith("@") and name[1:]:
            parameters.add(name[1:])
    return tuple(sorted(parameters))


def _is_bind_parameter(node: exp.Expression, required_parameter: str) -> bool:
    if not isinstance(node, exp.Column):
        return False
    name = node.name
    if not isinstance(name, str) or not name:
        return False
    if name.startswith("@"):
        return name[1:] == required_parameter
    if name.startswith("$") and name[1:].isdigit():
        return name[1:] == required_parameter
    return name == "?" and required_parameter == "?"


def _is_scalar_no_from(select: exp.Select) -> bool:
    return bool(select.args.get("from") is None)


def _has_group_by(select: exp.Select) -> bool:
    return bool(select.args.get("group") is not None)


def _contains_aggregate(expression: exp.Expression) -> bool:
    if isinstance(expression, exp.AggFunc):
        return True
    if isinstance(expression, exp.Func) and expression.name.lower() in {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "array_agg",
        "string_agg",
    }:
        return True
    return any(
        isinstance(child, exp.AggFunc) for child in expression.walk() if child is not expression
    )


def _is_single_row_aggregate(select: exp.Select) -> bool:
    return not _has_group_by(select) and any(
        _contains_aggregate(expression) for expression in select.args.get("expressions", ())
    )


def _physical_sources_in_scope(scope: Scope) -> dict[str, tuple[exp.Expression, str]]:
    """Return physical-table reads visible directly in one SQLGlot scope."""

    physical: dict[str, tuple[exp.Expression, str]] = {}
    for alias, (source_node, source_object) in scope.selected_sources.items():
        if isinstance(source_object, exp.Table):
            physical[alias.lower()] = (source_node, source_object.name.lower())
    return physical


def _top_level_select(statement: exp.Expression) -> exp.Select | None:
    if isinstance(statement, exp.Select):
        return statement
    if isinstance(statement, exp.With) and isinstance(statement.this, exp.Select):
        return statement.this
    return None


def _top_level_limit(statement: exp.Expression) -> exp.Limit | None:
    """Return the final result limit, excluding branch and nested limits."""

    select = _top_level_select(statement)
    if select is not None:
        return select.args.get("limit")
    if isinstance(statement, exp.Union):
        if statement.args.get("limit") is not None:
            return statement.args["limit"]
        operand = statement
        while isinstance(operand, exp.Union):
            operand = operand.args.get("expression")
        if isinstance(operand, exp.Select):
            return operand.args.get("limit")
    return None


def _extract_effective_limit(statement: exp.Expression) -> int | None:
    limit = _top_level_limit(statement)
    if limit is None:
        return None
    limit_expression = limit.args.get("this")
    if not isinstance(limit_expression, exp.Literal) or limit_expression.is_string:
        return None
    try:
        value = int(limit_expression.this)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _deduplicate_policy_errors(errors: list[SqlPolicyError]) -> list[SqlPolicyError]:
    """Keep the first occurrence of each error in deterministic traversal order."""

    deduplicated: list[SqlPolicyError] = []
    seen: set[tuple[str, str | None, str]] = set()
    for error in errors:
        key = (error.code, error.context, error.message)
        if key not in seen:
            seen.add(key)
            deduplicated.append(error)
    return deduplicated


class SqlPolicyValidationService:
    """Validate parsed SQL policy only; this service never executes SQL."""

    def __init__(
        self,
        catalog_provider: SqlCatalogProvider,
        settings: SqlAnalyticsSettings | None = None,
    ) -> None:
        self._catalog_provider = catalog_provider
        self._settings = settings or SqlAnalyticsSettings()

    def validate(self, sql: str) -> SqlPolicyValidationResult:
        """Validate direct scope and final-result bounds for one SQL statement."""

        catalog = self._catalog_provider.get_catalog()
        dialect = _map_dialect(catalog.dialect)
        if dialect is None:
            return self._invalid(
                "UNSUPPORTED_DIALECT", f"Unsupported catalog dialect: {catalog.dialect}"
            )

        try:
            parsed = sqlglot.parse(sql, read=dialect)
        except sqlglot.ParseError:
            try:
                tolerant_ast = sqlglot.parse(sql, read=dialect, error_level="ignore")
            except sqlglot.ParseError:
                tolerant_ast = []
            if (
                len(tolerant_ast) == 1
                and isinstance(tolerant_ast[0], (exp.Select, exp.With, exp.Union))
                and _top_level_limit(tolerant_ast[0]) is not None
            ):
                parsed = tolerant_ast
            else:
                return self._invalid("PARSE_ERROR", "SQL could not be parsed")

        if not parsed or parsed[0] is None:
            return self._invalid("EMPTY_SQL", "SQL must not be empty")
        if len(parsed) > 1:
            return self._invalid("MULTIPLE_STATEMENTS", "Multiple SQL statements are not allowed")

        statement = parsed[0]
        if not isinstance(statement, (exp.Select, exp.With, exp.Union)):
            return self._invalid("PARSE_ERROR", "SQL could not be parsed")

        try:
            normalized_sql = sqlglot.transpile(statement.sql(), read=dialect, write=dialect)[0]
        except Exception:
            normalized_sql = None

        scope_errors, scoped_tables = self._validate_scopes(statement, catalog)
        limit_errors, effective_limit = self._validate_result_bounds(statement)
        errors = _deduplicate_policy_errors([*scope_errors, *limit_errors])
        return SqlPolicyValidationResult(
            valid=not errors,
            normalized_sql=normalized_sql,
            scoped_tables=tuple(sorted(scoped_tables)),
            detected_parameters=_extract_bound_parameters(statement),
            effective_limit=effective_limit,
            errors=tuple(errors),
        )

    @staticmethod
    def _invalid(code: str, message: str) -> SqlPolicyValidationResult:
        return SqlPolicyValidationResult(
            valid=False,
            errors=(SqlPolicyError(code=code, message=message),),
        )

    def _validate_scopes(
        self, statement: exp.Expression, catalog: SqlSchemaCatalog
    ) -> tuple[list[SqlPolicyError], set[str]]:
        errors: list[SqlPolicyError] = []
        scoped_tables: set[str] = set()
        try:
            scopes = list(traverse_scope(statement))
        except Exception as exc:
            return [
                SqlPolicyError(
                    code="UNSUPPORTED_SQL_FEATURE",
                    message=f"Scope analysis failed: {type(exc).__name__}",
                )
            ], scoped_tables

        for scope in scopes:
            physical_sources = _physical_sources_in_scope(scope)
            for alias, (_, physical_name) in physical_sources.items():
                if physical_name not in catalog.allowed_table_names():
                    continue
                table = catalog.get_table(physical_name)
                if not table.user_scoped:
                    continue
                if table.scope_strategy != "direct":
                    errors.append(
                        SqlPolicyError(
                            code="USER_SCOPE_UNSUPPORTED",
                            message=(
                                f"Table '{physical_name}' has unsupported scope strategy: "
                                f"{table.scope_strategy}"
                            ),
                            context=physical_name,
                        )
                    )
                    continue
                user_scope_columns = {column.name.lower() for column in table.user_scope_columns()}
                if not user_scope_columns:
                    continue
                proven, code = self._check_scope_predicates(
                    scope,
                    alias,
                    user_scope_columns,
                    len(physical_sources),
                )
                if proven:
                    scoped_tables.add(physical_name)
                    continue
                errors.append(
                    SqlPolicyError(
                        code=code,
                        message=self._scope_error_message(code, physical_name),
                        context=physical_name,
                    )
                )
        return errors, scoped_tables

    def _check_scope_predicates(
        self,
        scope: Scope,
        table_alias: str,
        user_scope_columns: set[str],
        physical_source_count: int,
    ) -> tuple[bool, str]:
        if not isinstance(scope.expression, exp.Select):
            return False, "USER_SCOPE_REQUIRED"
        where = scope.expression.args.get("where")
        if where is None:
            return False, "USER_SCOPE_REQUIRED"
        predicates = self._flatten_boolean(where.this)
        if any(isinstance(predicate, exp.Or) for predicate in predicates):
            return False, "USER_SCOPE_AMBIGUOUS"

        required_parameter = self._settings.required_scope_parameter
        for predicate in predicates:
            if not isinstance(predicate, exp.EQ):
                continue
            for column_side, value_side in (
                (predicate.left, predicate.right),
                (predicate.right, predicate.left),
            ):
                if (
                    not isinstance(column_side, exp.Column)
                    or column_side.name.lower() not in user_scope_columns
                ):
                    continue
                if column_side.table:
                    qualifier = (
                        column_side.table.this
                        if hasattr(column_side.table, "this")
                        else str(column_side.table)
                    )
                    if qualifier.lower() != table_alias:
                        continue
                elif physical_source_count > 1:
                    continue

                if _is_bind_parameter(value_side, required_parameter):
                    return True, ""
                if isinstance(value_side, exp.Column):
                    parameter_name = value_side.name
                    if (
                        parameter_name
                        and parameter_name.startswith("@")
                        and parameter_name[1:] != required_parameter
                    ):
                        return False, "USER_SCOPE_PARAMETER_REQUIRED"
                    if (
                        parameter_name
                        and parameter_name.startswith("$")
                        and parameter_name[1:] != required_parameter
                    ):
                        return False, "USER_SCOPE_PARAMETER_REQUIRED"
                    if parameter_name == "?" and required_parameter != "?":
                        return False, "USER_SCOPE_PARAMETER_REQUIRED"
                if isinstance(value_side, exp.Literal):
                    return False, "USER_SCOPE_LITERAL_NOT_ALLOWED"
        return False, "USER_SCOPE_REQUIRED"

    def _scope_error_message(self, code: str, table_name: str) -> str:
        if code == "USER_SCOPE_AMBIGUOUS":
            return f"Table '{table_name}' scope predicate contains unsafe boolean logic (OR)"
        if code == "USER_SCOPE_LITERAL_NOT_ALLOWED":
            return (
                f"Table '{table_name}' uses literal value instead of bind parameter for user scope"
            )
        if code == "USER_SCOPE_PARAMETER_REQUIRED":
            return (
                f"Table '{table_name}' requires the @{self._settings.required_scope_parameter} "
                "parameter for user scope"
            )
        return (
            f"User-scoped table '{table_name}' requires a predicate on a user-scope "
            f"column against @{self._settings.required_scope_parameter}"
        )

    def _flatten_boolean(self, expression: exp.Expression) -> list[exp.Expression]:
        if isinstance(expression, exp.And):
            predicates: list[exp.Expression] = []
            if expression.this:
                predicates.extend(self._flatten_boolean(expression.this))
            right = expression.args.get("expression")
            if right:
                predicates.extend(self._flatten_boolean(right))
            return predicates
        return [expression]

    def _validate_result_bounds(
        self, statement: exp.Expression
    ) -> tuple[list[SqlPolicyError], int | None]:
        limit = _top_level_limit(statement)
        effective_limit = _extract_effective_limit(statement)
        if limit is not None and effective_limit is None:
            return [
                SqlPolicyError(code="INVALID_LIMIT", message="LIMIT must be a positive integer")
            ], None
        if effective_limit is not None and effective_limit > self._settings.max_result_limit:
            return [
                SqlPolicyError(
                    code="RESULT_LIMIT_TOO_HIGH",
                    message=(
                        f"LIMIT {effective_limit} exceeds maximum allowed "
                        f"{self._settings.max_result_limit}"
                    ),
                )
            ], None
        if self._needs_limit(statement) and limit is None:
            return [
                SqlPolicyError(
                    code="RESULT_LIMIT_REQUIRED", message="Query requires a LIMIT clause"
                )
            ], None
        return [], effective_limit

    @staticmethod
    def _needs_limit(statement: exp.Expression) -> bool:
        if isinstance(statement, exp.Union):
            return True
        select = _top_level_select(statement)
        if select is None:
            return False
        if _is_scalar_no_from(select):
            return False
        return not _is_single_row_aggregate(select)
