"""Tests for the unified QueryGuard preparation facade."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from queryguard import (
    QueryGuard,
    QueryPreparationResult,
    SqlGenerationService,
    SqlPolicyValidationService,
    SqlValidationService,
)

EXAMPLE_PATH = Path(__file__).parents[2] / "examples" / "commerce_catalog.yaml"
VALID_SQL = "SELECT id FROM orders WHERE account_id = @user_id LIMIT 100"
POLICY_INVALID_SQL = "SELECT id FROM orders WHERE account_id = @user_id"
STRUCTURALLY_INVALID_SQL = "SELECT * FROM orders WHERE account_id = @user_id LIMIT 100"


class StubProvider:
    def __init__(self, sql: str = VALID_SQL, error: Exception | None = None) -> None:
        self.sql = sql
        self.error = error
        self.calls: list[tuple[dict[str, str], ...]] = []

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return json.dumps({"sql": self.sql})


def _run(awaitable):
    return asyncio.run(awaitable)


def _guard(provider: StubProvider) -> QueryGuard:
    return QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)


def test_successful_prepare_returns_approved_pipeline_result():
    result = _run(_guard(StubProvider()).prepare("Show order counts by status"))
    assert result.approved is True
    assert result.stage == "approved"
    assert result.generated is not None
    assert result.structural is not None and result.structural.valid is True
    assert result.policy is not None and result.policy.valid is True


def test_prepare_returns_generated_sql_structural_and_policy_results():
    result = _run(_guard(StubProvider()).prepare("List my orders"))
    assert result.generated.sql == VALID_SQL
    assert result.structural.normalized_sql is not None
    assert result.policy.effective_limit == 100


def test_approved_requires_both_validators_to_pass():
    result = _run(_guard(StubProvider(POLICY_INVALID_SQL)).prepare("List my orders"))
    assert result.approved is False
    assert result.stage == "policy_validation"
    assert result.structural.valid is True
    assert result.policy.valid is False


def test_generation_failure_short_circuits_all_downstream_stages():
    provider = StubProvider(error=RuntimeError("provider unavailable"))
    guard = _guard(provider)
    structural_calls: list[str] = []
    policy_calls: list[str] = []
    guard._structural_validator.validate = lambda sql: structural_calls.append(sql)  # type: ignore[method-assign]
    guard._policy_validator.validate = lambda sql: policy_calls.append(sql)  # type: ignore[method-assign]

    result = _run(guard.prepare("List my orders"))
    assert result.approved is False
    assert result.stage == "generation"
    assert result.generated is None
    assert result.structural is None
    assert result.policy is None
    assert structural_calls == []
    assert policy_calls == []


def test_malformed_provider_response_stops_at_generation():
    class MalformedProvider(StubProvider):
        async def generate(self, messages):
            self.calls.append(messages)
            return "not JSON"

    result = _run(_guard(MalformedProvider()).prepare("List my orders"))
    assert result.approved is False
    assert result.stage == "generation"
    assert result.structural is None
    assert result.policy is None
    assert result.errors


def test_structural_failure_prevents_policy_call():
    guard = _guard(StubProvider(STRUCTURALLY_INVALID_SQL))
    policy_calls: list[str] = []
    original_policy = guard._policy_validator.validate
    guard._policy_validator.validate = lambda sql: policy_calls.append(sql) or original_policy(sql)  # type: ignore[method-assign]

    result = _run(guard.prepare("List my orders"))
    assert result.approved is False
    assert result.stage == "structural_validation"
    assert result.generated is not None
    assert result.structural is not None and result.structural.valid is False
    assert result.policy is None
    assert policy_calls == []


def test_policy_failure_returns_structured_policy_result_without_repair():
    provider = StubProvider(POLICY_INVALID_SQL)
    result = _run(_guard(provider).prepare("List my orders"))
    assert result.stage == "policy_validation"
    assert result.policy is not None
    assert any(error.code == "RESULT_LIMIT_REQUIRED" for error in result.policy.errors)
    assert len(provider.calls) == 1


def test_provider_is_called_exactly_once_with_no_retry():
    provider = StubProvider(error=RuntimeError("provider unavailable"))
    _run(_guard(provider).prepare("List my orders"))
    assert len(provider.calls) == 1


def test_from_yaml_uses_real_catalog_context():
    provider = StubProvider()
    result = _run(_guard(provider).prepare("List my orders"))
    assert result.approved is True
    assert "Table: orders" in provider.calls[0][0]["content"]
    assert "Database dialect: postgresql" in provider.calls[0][0]["content"]


def test_symbolic_scope_parameter_remains_in_generated_sql_and_prompt():
    provider = StubProvider()
    result = _run(_guard(provider).prepare("List my orders"))
    assert "@user_id" in result.generated.sql
    assert "@user_id" in provider.calls[0][0]["content"]


def test_conversation_history_propagates_without_mutation():
    provider = StubProvider()
    history = ({"role": "user", "content": "Earlier question"},)
    _run(_guard(provider).prepare("List my orders", conversation_history=history))
    assert provider.calls[0][1] == history[0]
    assert provider.calls[0][1] is not history[0]
    assert history == ({"role": "user", "content": "Earlier question"},)


def test_validate_sql_valid_path_does_not_generate():
    provider = StubProvider()
    result = _guard(provider).validate_sql(VALID_SQL)
    assert result.approved is True
    assert result.stage == "approved"
    assert result.generated is None
    assert result.structural.valid is True
    assert result.policy.valid is True
    assert provider.calls == []


def test_validate_sql_structural_failure():
    result = _guard(StubProvider()).validate_sql(STRUCTURALLY_INVALID_SQL)
    assert result.approved is False
    assert result.stage == "structural_validation"
    assert result.structural.valid is False
    assert result.policy is None


def test_validate_sql_policy_failure():
    result = _guard(StubProvider()).validate_sql(POLICY_INVALID_SQL)
    assert result.approved is False
    assert result.stage == "policy_validation"
    assert result.structural.valid is True
    assert result.policy.valid is False


def test_validate_sql_does_not_call_generation_provider():
    provider = StubProvider()
    _guard(provider).validate_sql(VALID_SQL)
    assert provider.calls == []


@pytest.mark.parametrize(
    ("provider", "expected_stage"),
    [
        (StubProvider(), "approved"),
        (StubProvider(POLICY_INVALID_SQL), "policy_validation"),
        (StubProvider(STRUCTURALLY_INVALID_SQL), "structural_validation"),
        (StubProvider(error=RuntimeError("failure")), "generation"),
    ],
)
def test_stage_values_are_deterministic(provider, expected_stage):
    result = _run(_guard(provider).prepare("List my orders"))
    assert result.stage == expected_stage


def test_query_preparation_result_consistency_validators():
    with pytest.raises(ValidationError):
        QueryPreparationResult(approved=True, stage="approved")
    with pytest.raises(ValidationError):
        QueryPreparationResult(approved=False, stage="generation")


def test_low_level_public_apis_remain_available():
    assert SqlGenerationService is not None
    assert SqlValidationService is not None
    assert SqlPolicyValidationService is not None


def test_facade_has_no_execution_dependency():
    source = Path(__file__).parents[2] / "src" / "queryguard" / "facade.py"
    text = source.read_text(encoding="utf-8").lower()
    assert "sqlalchemy" not in text
    assert "queryguard_sqlalchemy" not in text
    assert "create_engine" not in text
