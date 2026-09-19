"""Tests for generic, provider-neutral execution orchestration."""

import asyncio

import pytest

from queryguard import SqlAnalyticsSettings, SqlExecutionResult, SqlExecutionService
from queryguard.execution import RawExecutionResult, SqlExecutionAdapterError


class StubExecutor:
    def __init__(self, result: RawExecutionResult | None = None, error: Exception | None = None) -> None:
        self.result = result or RawExecutionResult((), (), False)
        self.error = error
        self.calls: list[tuple[str, dict[str, object], int, int]] = []

    async def execute(self, sql, parameters, *, max_rows, timeout_ms):
        self.calls.append((sql, dict(parameters), max_rows, timeout_ms))
        if self.error is not None:
            raise self.error
        return self.result


def _run(service: SqlExecutionService, sql: str, parameters: dict[str, object]) -> SqlExecutionResult:
    return asyncio.run(service.execute(sql, parameters))


def test_service_returns_public_normalized_result_and_execution_timing():
    executor = StubExecutor(RawExecutionResult(("id",), ({"id": 1},), False))
    result = _run(SqlExecutionService(executor), "SELECT id FROM orders", {})
    assert result == SqlExecutionResult(
        success=True,
        columns=("id",),
        rows=({"id": 1},),
        row_count=1,
        execution_ms=result.execution_ms,
    )
    assert result.execution_ms >= 0


def test_service_binds_exact_sorted_parameters_without_interpolation():
    executor = StubExecutor()
    result = _run(
        SqlExecutionService(executor),
        "SELECT id FROM orders WHERE account_id = @user_id AND status = @status",
        {"status": "done", "user_id": "account-123"},
    )
    assert result.success is True
    assert executor.calls == [
        (
            "SELECT id FROM orders WHERE account_id = @user_id AND status = @status",
            {"status": "done", "user_id": "account-123"},
            100,
            5000,
        )
    ]
    assert "account-123" not in executor.calls[0][0]


@pytest.mark.parametrize(
    ("sql", "parameters"),
    [
        ("SELECT id FROM orders WHERE account_id = @user_id", {}),
        ("SELECT 1", {"user_id": "account-123"}),
    ],
)
def test_missing_and_extra_parameters_are_rejected_before_execution(sql, parameters):
    executor = StubExecutor()
    result = _run(SqlExecutionService(executor), sql, parameters)
    assert result.success is False
    assert result.error_code == "PARAMETER_BINDING_ERROR"
    assert executor.calls == []


def test_service_makes_exactly_one_call_without_retry():
    executor = StubExecutor(error=RuntimeError("database down"))
    result = _run(SqlExecutionService(executor), "SELECT 1", {})
    assert result.success is False
    assert result.error_code == "EXECUTION_FAILED"
    assert result.execution_ms >= 0
    assert len(executor.calls) == 1


@pytest.mark.parametrize("error_code", ["EXECUTION_TIMEOUT", "READ_ONLY_VIOLATION", "PARAMETER_BINDING_ERROR"])
def test_controlled_adapter_errors_keep_stable_codes(error_code):
    result = _run(
        SqlExecutionService(StubExecutor(error=SqlExecutionAdapterError(error_code))),
        "SELECT 1",
        {},
    )
    assert result.success is False
    assert result.error_code == error_code


def test_service_does_not_automatically_validate_sql():
    executor = StubExecutor()
    result = _run(SqlExecutionService(executor), "not SQL but an executor input", {})
    assert result.success is True
    assert len(executor.calls) == 1


def test_service_passes_configured_fetch_and_timeout_limits():
    settings = SqlAnalyticsSettings(default_limit=7, max_rows=7, statement_timeout_ms=1234)
    executor = StubExecutor()
    _run(SqlExecutionService(executor, settings), "SELECT 1", {})
    assert executor.calls[0][2:] == (7, 1234)
