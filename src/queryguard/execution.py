"""Generic execution orchestration for already-validated SQL."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from queryguard.contracts import SqlExecutionResult
from queryguard.settings import SqlAnalyticsSettings


class SqlExecutionAdapterError(RuntimeError):
    """Internal adapter failure carrying a safe public execution error code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class RawExecutionResult:
    """Provider-neutral, already-normalized bounded result returned by an executor."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    truncated: bool


class SqlExecutor(Protocol):
    """Execute one SQL statement without validation, retries, or public result leakage."""

    async def execute(
        self,
        sql: str,
        parameters: dict[str, object],
        *,
        max_rows: int,
        timeout_ms: int,
    ) -> RawExecutionResult:
        """Return a normalized bounded result or raise a controlled adapter error."""
        ...


def _is_identifier_char(character: str) -> bool:
    return character.isalnum() or character == "_"


def _dollar_quote_delimiter(sql: str, start: int) -> str | None:
    if sql[start] != "$":
        return None
    index = start + 1
    if index < len(sql) and sql[index] == "$":
        return "$$"
    if index >= len(sql) or not (sql[index].isalpha() or sql[index] == "_"):
        return None
    index += 1
    while index < len(sql) and _is_identifier_char(sql[index]):
        index += 1
    return sql[start : index + 1] if index < len(sql) and sql[index] == "$" else None


def _translate_policy_parameters(sql: str) -> tuple[str, tuple[str, ...]]:
    """Convert executable ``@name`` tokens to ``:name`` without touching SQL text."""

    output: list[str] = []
    parameters: list[str] = []
    index = 0
    while index < len(sql):
        character = sql[index]
        if character in {"'", '"'}:
            end = index + 1
            while end < len(sql):
                if sql[end] == character:
                    if end + 1 < len(sql) and sql[end + 1] == character:
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            output.append(sql[index:end])
            index = end
            continue
        if character == "-" and index + 1 < len(sql) and sql[index + 1] == "-":
            end = sql.find("\n", index + 2)
            end = len(sql) if end == -1 else end
            output.append(sql[index:end])
            index = end
            continue
        if character == "/" and index + 1 < len(sql) and sql[index + 1] == "*":
            end = sql.find("*/", index + 2)
            end = len(sql) if end == -1 else end + 2
            output.append(sql[index:end])
            index = end
            continue
        if character == "$":
            delimiter = _dollar_quote_delimiter(sql, index)
            if delimiter is not None:
                content_start = index + len(delimiter)
                end = sql.find(delimiter, content_start)
                end = len(sql) if end == -1 else end + len(delimiter)
                output.append(sql[index:end])
                index = end
                continue
        previous = sql[index - 1] if index else ""
        if (
            character == "@"
            and (not previous or not _is_identifier_char(previous))
            and index + 1 < len(sql)
            and (sql[index + 1].isalpha() or sql[index + 1] == "_")
        ):
            end = index + 2
            while end < len(sql) and _is_identifier_char(sql[end]):
                end += 1
            name = sql[index + 1 : end]
            output.append(f":{name}")
            parameters.append(name)
            index = end
            continue
        output.append(character)
        index += 1
    return "".join(output), tuple(parameters)


def _required_policy_parameters(sql: str) -> tuple[str, ...]:
    """Return sorted, unique executable ``@name`` parameter names."""

    _, names = _translate_policy_parameters(sql)
    return tuple(sorted(set(names)))


class SqlExecutionService:
    """Execute SQL that the caller has already structurally and policy validated."""

    def __init__(self, executor: SqlExecutor, settings: SqlAnalyticsSettings | None = None) -> None:
        self._executor = executor
        self._settings = settings or SqlAnalyticsSettings()

    async def execute(self, sql: str, parameters: dict[str, object]) -> SqlExecutionResult:
        """Run one executor call with exact bound parameters and no automatic validation."""

        required = _required_policy_parameters(sql)
        if set(required) != set(parameters):
            return SqlExecutionResult(success=False, error_code="PARAMETER_BINDING_ERROR")
        bound_parameters = {name: parameters[name] for name in required}

        started_at = perf_counter()
        try:
            raw_result = await self._executor.execute(
                sql,
                bound_parameters,
                max_rows=self._settings.max_rows,
                timeout_ms=self._settings.statement_timeout_ms,
            )
        except SqlExecutionAdapterError as exc:
            return SqlExecutionResult(
                success=False,
                execution_ms=(perf_counter() - started_at) * 1000,
                error_code=exc.error_code,
            )
        except Exception:
            return SqlExecutionResult(
                success=False,
                execution_ms=(perf_counter() - started_at) * 1000,
                error_code="EXECUTION_FAILED",
            )

        return SqlExecutionResult(
            success=True,
            columns=raw_result.columns,
            rows=raw_result.rows,
            row_count=len(raw_result.rows),
            truncated=raw_result.truncated,
            execution_ms=(perf_counter() - started_at) * 1000,
        )
