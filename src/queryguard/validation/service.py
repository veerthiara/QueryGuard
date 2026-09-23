"""SQL Validation Service — orchestration module.

Orchestrates the structural validation pipeline:

    parse SQL
        ↓
    validate statement shape
        ↓
    resolve scopes/tables
        ↓
    validate columns
        ↓
    compute authoritative metadata
        ↓
    compare generated metadata if present
        ↓
    build SqlValidationResult

This module owns the high-level algorithm. Implementation details live in
the sibling modules (parsing, statements, tables, columns, scopes, lineage, metadata).
"""

from __future__ import annotations

import sqlglot
from sqlglot import expressions as exp
from sqlglot.optimizer.scope import traverse_scope

from queryguard.catalog import SqlCatalogProvider
from queryguard.contracts import (
    GeneratedSql,
    SqlValidationError,
    SqlValidationResult,
)
from queryguard.validation.columns import (
    _COLUMN_AMBIGUOUS,
    _COLUMN_MISSING,
    resolve_qualified_column,
    resolve_unqualified_column,
)
from queryguard.validation.lineage import build_scope_output_columns
from queryguard.validation.metadata import compare_metadata, deduplicate_errors
from queryguard.validation.parsing import map_dialect, normalize_identifier, parse_sql
from queryguard.validation.scopes import (
    get_visible_sources_in_scope,
    is_bind_parameter_column,
    source_label,
)
from queryguard.validation.statements import (
    check_dangerous_functions,
    check_forbidden_constructs,
    check_system_schema_access,
    check_wildcards,
    get_statement_type,
    validate_statement_root,
)
from queryguard.validation.tables import collect_physical_tables, validate_physical_tables


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
        dialect = map_dialect(catalog.dialect)
        if dialect is None:
            return SqlValidationResult(
                valid=False,
                errors=(
                    SqlValidationError(
                        code="UNSUPPORTED_DIALECT",
                        message=f"Unsupported catalog dialect: {catalog.dialect}",
                    ),
                ),
            )

        # 1. Parse SQL
        ast, parse_error = parse_sql(sql, dialect)
        if parse_error is not None:
            return SqlValidationResult(
                valid=False,
                normalized_sql=None,
                errors=(parse_error,),
            )

        assert ast is not None  # guaranteed by parse_sql contract
        stmt = ast[0]

        # 2. Validate statement structure
        errors = validate_statement_root(stmt)
        if errors:
            return SqlValidationResult(
                valid=False,
                normalized_sql=None,
                errors=tuple(errors),
            )

        # 3. Check for forbidden constructs anywhere in AST
        errors.extend(check_forbidden_constructs(stmt))

        # 4. Check system schema access
        errors.extend(check_system_schema_access(stmt))

        # 5. Check dangerous functions
        errors.extend(check_dangerous_functions(stmt))

        # 6. Check wildcards
        errors.extend(check_wildcards(stmt))

        if errors:
            return SqlValidationResult(
                valid=False,
                normalized_sql=None,
                errors=tuple(deduplicate_errors(errors)),
            )

        # 7. Scope analysis
        scope_errors, parsed_tables, parsed_columns = self._analyze_scopes(stmt, catalog)
        errors.extend(scope_errors)

        # 8. Metadata comparison warnings
        warnings = compare_metadata(
            model_tables=model_tables,
            model_columns=model_columns,
            parsed_tables=parsed_tables,
            parsed_columns=parsed_columns,
        )

        # 9. Generate normalized SQL
        normalized_sql = None
        try:
            normalized_sql = sqlglot.transpile(stmt.sql(), read=dialect, write=dialect)[0]
        except Exception:
            normalized_sql = None

        valid = len(errors) == 0

        return SqlValidationResult(
            valid=valid,
            normalized_sql=normalized_sql,
            statement_type=get_statement_type(stmt),
            referenced_tables=tuple(sorted(parsed_tables)),
            referenced_columns=tuple(sorted(parsed_columns)),
            errors=tuple(deduplicate_errors(errors)),
            warnings=tuple(warnings),
        )

    def _analyze_scopes(
        self,
        stmt: exp.Expression,
        catalog,
    ) -> tuple[list[SqlValidationError], set[str], set[str]]:
        """Analyze all query scopes for table and column validation."""
        errors: list[SqlValidationError] = []
        parsed_tables: set[str] = set()
        parsed_columns: set[str] = set()

        try:
            scopes = list(traverse_scope(stmt))
        except Exception as e:
            errors.append(
                SqlValidationError(
                    code="UNSUPPORTED_SQL_FEATURE",
                    message=f"Scope analysis failed: {type(e).__name__}",
                )
            )
            return errors, parsed_tables, parsed_columns

        # First pass: collect all physical tables from scope-aware selected sources
        physical_tables = collect_physical_tables(scopes)
        parsed_tables, table_errors = validate_physical_tables(physical_tables, catalog)
        errors.extend(table_errors)

        # Second pass: validate scope-local columns and build output lineage for parent scopes.
        scope_outputs: dict[int, dict[str, frozenset[str]]] = {}
        for scope_idx, scope in enumerate(scopes):
            visible_sources = get_visible_sources_in_scope(scope)
            outer_scopes = scopes[scope_idx + 1 :]

            # Get external columns for this scope (correlated references)
            external_col_names = set()
            for ext_col in getattr(scope, "external_columns", []):
                external_col_names.add(normalize_identifier(ext_col.name))

            for col in scope.columns:
                if is_bind_parameter_column(col):
                    continue
                col_name = normalize_identifier(col.name)
                table_qualifier = normalize_identifier(col.table) if col.table else None

                if table_qualifier:
                    resolution = resolve_qualified_column(
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
                                source_entry = get_visible_sources_in_scope(outer_scope).get(
                                    table_qualifier
                                )
                                if source_entry is not None:
                                    break
                        source_node = source_entry[0] if source_entry is not None else None
                        source_obj = source_entry[1] if source_entry is not None else None
                        label = source_label(source_node, source_obj)
                        errors.append(
                            SqlValidationError(
                                code="COLUMN_NOT_ALLOWED",
                                message=f"Column '{col.name}' not found in {label} '{table_qualifier}'",
                                context=f"{table_qualifier}.{col.name}",
                            )
                        )
                    elif resolution is None:
                        errors.append(
                            SqlValidationError(
                                code="COLUMN_NOT_ALLOWED",
                                message=f"Unknown table reference '{table_qualifier}'",
                                context=f"{table_qualifier}.{col.name}",
                            )
                        )
                    else:
                        parsed_columns.update(resolution)
                else:
                    # Unqualified column
                    if col_name in external_col_names and not visible_sources:
                        continue
                    result = resolve_unqualified_column(
                        col_name=col.name,
                        catalog=catalog,
                        visible_sources=visible_sources,
                        scope_outputs=scope_outputs,
                    )
                    if result == _COLUMN_AMBIGUOUS:
                        errors.append(
                            SqlValidationError(
                                code="UNQUALIFIED_COLUMN_AMBIGUOUS",
                                message=f"Column '{col.name}' is ambiguous across multiple tables",
                                context=col.name,
                            )
                        )
                    elif result is None:
                        errors.append(
                            SqlValidationError(
                                code="COLUMN_NOT_ALLOWED",
                                message=f"Column '{col.name}' not found in any visible table",
                                context=col.name,
                            )
                        )
                    else:
                        parsed_columns.update(result)

            scope_outputs[id(scope)] = build_scope_output_columns(
                scope=scope,
                catalog=catalog,
                visible_sources=visible_sources,
                outer_scopes=outer_scopes,
                scope_outputs=scope_outputs,
            )

        return errors, parsed_tables, parsed_columns
