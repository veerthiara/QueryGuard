"""Tests for the optional synchronous SQLAlchemy execution adapter."""

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import TimeoutError as SqlAlchemyTimeoutError

import queryguard
from queryguard import SqlAnalyticsSettings, SqlExecutionService
from queryguard.adapters.sqlalchemy import SqlAlchemyExecutor
from queryguard.execution import _translate_policy_parameters


class FakeResult:
    def __init__(self, columns: tuple[str, ...], rows: list[object]) -> None:
        self.columns = columns
        self.rows = rows
        self.fetch_sizes: list[int] = []

    def keys(self):
        return self.columns

    def fetchmany(self, size: int):
        self.fetch_sizes.append(size)
        return self.rows[:size]


class FakeSession:
    def __init__(self, result: FakeResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class _PostgreSqlDialect:
    name = "postgresql"


class _PostgreSqlBind:
    dialect = _PostgreSqlDialect()


class PostgreSqlFakeSession(FakeSession):
    bind = _PostgreSqlBind()

    def execute(self, statement, parameters=None):
        self.calls.append((str(statement), dict(parameters or {})))
        if str(statement).startswith("SET TRANSACTION") or str(statement).startswith("SELECT set_config"):
            return FakeResult((), [])
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class ReadOnlyDatabaseError(Exception):
    pgcode = "25006"


def _run(service: SqlExecutionService, sql: str, parameters: dict[str, object]):
    return asyncio.run(service.execute(sql, parameters))


def _service(session: object, max_rows: int = 100) -> SqlExecutionService:
    return SqlExecutionService(
        SqlAlchemyExecutor(session),
        SqlAnalyticsSettings(default_limit=max_rows, max_rows=max_rows),
    )


@pytest.mark.parametrize(
    ("rows", "expected"),
    [([], ()), ([(1,)], ({"value": 1},)), ([(1,), (2,)], ({"value": 1}, {"value": 2}))],
)
def test_adapter_handles_zero_one_and_many_rows(rows, expected):
    session = FakeSession(FakeResult(("value",), rows))
    result = _run(_service(session), "SELECT value FROM values", {})
    assert result.success is True
    assert result.columns == ("value",)
    assert result.rows == expected
    assert result.row_count == len(expected)
    assert result.truncated is False


def test_adapter_fetches_max_rows_plus_one_and_marks_truncation():
    fake_result = FakeResult(("value",), [(1,), (2,), (3,)])
    result = _run(_service(FakeSession(fake_result), max_rows=2), "SELECT value FROM values", {})
    assert result.rows == ({"value": 1}, {"value": 2})
    assert result.row_count == 2
    assert result.truncated is True
    assert fake_result.fetch_sizes == [3]


def test_adapter_converts_and_binds_executable_policy_parameters_only():
    session = FakeSession(FakeResult(("id",), [("order-1",)]))
    result = _run(
        _service(session),
        "SELECT id FROM orders WHERE account_id = @user_id",
        {"user_id": "account-123"},
    )
    assert result.success is True
    executed_sql, bound_parameters = session.calls[0]
    assert ":user_id" in executed_sql
    assert "account-123" not in executed_sql
    assert bound_parameters == {"user_id": "account-123"}


def test_placeholder_scanner_leaves_literals_identifiers_comments_and_dollar_quotes_unchanged():
    sql = (
        "SELECT '@user_id', \"@user_id\", @user_id -- @line\n"
        "/* @block */ $$ @dollar $$ $tag$ @tagged $tag$"
    )
    translated, parameters = _translate_policy_parameters(sql)
    assert translated == (
        "SELECT '@user_id', \"@user_id\", :user_id -- @line\n"
        "/* @block */ $$ @dollar $$ $tag$ @tagged $tag$"
    )
    assert parameters == ("user_id",)


def test_adapter_rejects_missing_and_extra_parameters_without_a_database_call():
    session = FakeSession(FakeResult(("id",), []))
    service = _service(session)
    missing = _run(service, "SELECT id FROM orders WHERE account_id = @user_id", {})
    extra = _run(service, "SELECT 1", {"user_id": "account-123"})
    assert missing.error_code == "PARAMETER_BINDING_ERROR"
    assert extra.error_code == "PARAMETER_BINDING_ERROR"
    assert session.calls == []


def test_adapter_maps_failure_timeout_and_read_only_errors_without_retry():
    failed = FakeSession(error=RuntimeError("database unavailable"))
    timeout = FakeSession(error=SqlAlchemyTimeoutError("statement timeout"))
    read_only = FakeSession(error=ReadOnlyDatabaseError("read only"))
    assert _run(_service(failed), "SELECT 1", {}).error_code == "EXECUTION_FAILED"
    assert _run(_service(timeout), "SELECT 1", {}).error_code == "EXECUTION_TIMEOUT"
    assert _run(_service(read_only), "SELECT 1", {}).error_code == "READ_ONLY_VIOLATION"
    assert len(failed.calls) == len(timeout.calls) == len(read_only.calls) == 1


def test_postgresql_adapter_uses_transaction_local_read_only_and_timeout_once():
    session = PostgreSqlFakeSession(FakeResult(("value",), [(1,)]))
    result = _run(_service(session), "SELECT 1 AS value", {})
    assert result.success is True
    assert [sql for sql, _ in session.calls] == [
        "SET TRANSACTION READ ONLY",
        "SELECT set_config('statement_timeout', :timeout_ms, true)",
        "SELECT 1 AS value",
    ]
    assert session.calls[1][1] == {"timeout_ms": "5000"}
    assert len([sql for sql, _ in session.calls if sql == "SELECT 1 AS value"]) == 1


def test_core_does_not_import_sqlalchemy_or_create_engines():
    import queryguard.execution as execution

    assert "sqlalchemy" not in inspect.getsource(queryguard).lower()
    source = inspect.getsource(execution)
    assert "sqlalchemy" not in source.lower()
    assert "create_engine" not in inspect.getsource(sys.modules["queryguard.adapters.sqlalchemy"])


def test_missing_sqlalchemy_dependency_has_controlled_import_guidance(monkeypatch):
    adapter_path = Path(__file__).parents[2] / "src" / "queryguard" / "adapters" / "sqlalchemy.py"
    spec = importlib.util.spec_from_file_location("queryguard.adapters._missing_sqlalchemy", adapter_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sqlalchemy", None)
    with pytest.raises(ImportError, match="SQLAlchemy support requires QueryGuard's sqlalchemy extra"):
        spec.loader.exec_module(module)
