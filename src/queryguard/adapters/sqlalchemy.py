"""Optional synchronous SQLAlchemy Session adapter for QueryGuard execution."""

from __future__ import annotations

from collections.abc import Mapping

try:
    from sqlalchemy import text
    from sqlalchemy.exc import InvalidRequestError, StatementError, TimeoutError as SqlAlchemyTimeoutError
except ImportError as exc:  # pragma: no cover - exercised in an isolated import test
    raise ImportError(
        "SQLAlchemy support requires QueryGuard's sqlalchemy extra. "
        "Install with: pip install 'queryguard[sqlalchemy]'"
    ) from exc

from queryguard.execution import (
    RawExecutionResult,
    SqlExecutionAdapterError,
    _translate_policy_parameters,
)


def _row_to_dict(row: object, columns: tuple[str, ...]) -> dict[str, object]:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return {column: mapping[column] for column in columns}
    if isinstance(row, Mapping):
        return {column: row[column] for column in columns}
    return {column: row[index] for index, column in enumerate(columns)}  # type: ignore[index]


def _is_postgresql_session(session: object) -> bool:
    bind = getattr(session, "bind", None)
    dialect = getattr(bind, "dialect", None)
    return getattr(dialect, "name", None) == "postgresql"


def _error_code(exception: Exception) -> str:
    if isinstance(exception, SqlAlchemyTimeoutError):
        return "EXECUTION_TIMEOUT"
    original = getattr(exception, "orig", exception)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate == "57014":
        return "EXECUTION_TIMEOUT"
    if sqlstate == "25006":
        return "READ_ONLY_VIOLATION"
    if isinstance(exception, StatementError) and isinstance(getattr(exception, "orig", None), InvalidRequestError):
        return "PARAMETER_BINDING_ERROR"
    return "EXECUTION_FAILED"


class SqlAlchemyExecutor:
    """Adapt an injected synchronous SQLAlchemy Session to ``SqlExecutor``."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def execute(
        self,
        sql: str,
        parameters: dict[str, object],
        *,
        max_rows: int,
        timeout_ms: int,
    ) -> RawExecutionResult:
        """Execute one user query once; this revision supports synchronous Sessions only."""

        execution_sql, _ = _translate_policy_parameters(sql)
        try:
            self._configure_postgresql_transaction(timeout_ms)
            result = self._session.execute(text(execution_sql), parameters)  # type: ignore[attr-defined]
            columns = tuple(str(column) for column in result.keys())
            fetched_rows = result.fetchmany(max_rows + 1)
        except Exception as exc:
            raise SqlExecutionAdapterError(_error_code(exc)) from exc

        bounded_rows = fetched_rows[:max_rows]
        return RawExecutionResult(
            columns=columns,
            rows=tuple(_row_to_dict(row, columns) for row in bounded_rows),
            truncated=len(fetched_rows) > max_rows,
        )

    def _configure_postgresql_transaction(self, timeout_ms: int) -> None:
        if not _is_postgresql_session(self._session):
            return
        self._session.execute(text("SET TRANSACTION READ ONLY"))  # type: ignore[attr-defined]
        self._session.execute(  # type: ignore[attr-defined]
            text("SELECT set_config('statement_timeout', :timeout_ms, true)"),
            {"timeout_ms": str(timeout_ms)},
        )
