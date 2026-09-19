"""Deterministic end-to-end acceptance tests for the commerce catalog.

Unit tests prove individual modules. These tests prove that the application
YAML boundary, generation contract, structural validator, policy validator,
and preparation result compose correctly. They are correctness and safety
tests, not an evaluation of LLM quality.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from queryguard import QueryGuard

pytestmark = pytest.mark.e2e


EXAMPLE_PATH = Path(__file__).parents[2] / "examples" / "commerce_catalog.yaml"


class ScenarioProvider:
    """A test-only provider that returns one deterministic strict-JSON response."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, str], ...]] = []

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        self.calls.append(tuple(copy.deepcopy(message) for message in messages))
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response)


@dataclass(frozen=True)
class AcceptedCase:
    name: str
    question: str
    sql: str
    expected_tables: frozenset[str]
    expected_scoped_tables: tuple[str, ...]
    expected_limit: int | None
    expected_columns: frozenset[str]
    sql_markers: tuple[str, ...] = ()

    @property
    def provider_response(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "referenced_tables": sorted(self.expected_tables),
            "explanation": self.name,
            "confidence": 1.0,
        }


ACCEPTED_CASES = (
    AcceptedCase(
        name="latest orders",
        question="Show my latest 20 orders",
        sql="SELECT id, total_cents FROM orders WHERE account_id = @user_id LIMIT 20",
        expected_tables=frozenset({"orders"}),
        expected_scoped_tables=("orders",),
        expected_limit=20,
        expected_columns=frozenset({"id", "total_cents", "account_id"}),
        sql_markers=("limit 20",),
    ),
    AcceptedCase(
        name="count orders",
        question="How many orders do I have?",
        sql="SELECT COUNT(*) FROM orders WHERE account_id = @user_id",
        expected_tables=frozenset({"orders"}),
        expected_scoped_tables=("orders",),
        expected_limit=None,
        expected_columns=frozenset({"account_id"}),
        sql_markers=("count(",),
    ),
    AcceptedCase(
        name="orders by status",
        question="Show order counts by status",
        sql=(
            "SELECT status, COUNT(*) AS order_count FROM orders "
            "WHERE account_id = @user_id GROUP BY status LIMIT 100"
        ),
        expected_tables=frozenset({"orders"}),
        expected_scoped_tables=("orders",),
        expected_limit=100,
        expected_columns=frozenset({"status", "account_id"}),
        sql_markers=("group by status", "count("),
    ),
    AcceptedCase(
        name="distinct statuses",
        question="What order statuses have I used?",
        sql="SELECT DISTINCT status FROM orders WHERE account_id = @user_id LIMIT 100",
        expected_tables=frozenset({"orders"}),
        expected_scoped_tables=("orders",),
        expected_limit=100,
        expected_columns=frozenset({"status", "account_id"}),
        sql_markers=("select distinct",),
    ),
    AcceptedCase(
        name="orders with items",
        question="Show my orders and their products",
        sql=(
            "SELECT o.id, i.product_name FROM orders o "
            "JOIN order_items i ON i.order_id = o.id "
            "WHERE o.account_id = @user_id AND i.account_id = @user_id LIMIT 100"
        ),
        expected_tables=frozenset({"orders", "order_items"}),
        expected_scoped_tables=("order_items", "orders"),
        expected_limit=100,
        expected_columns=frozenset({"id", "product_name", "order_id", "account_id"}),
        sql_markers=("join order_items",),
    ),
    AcceptedCase(
        name="correlated subquery",
        question="Show customers who have my orders",
        sql=(
            "SELECT c.name FROM customers c WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id = c.id "
            "AND o.account_id = @user_id) LIMIT 100"
        ),
        expected_tables=frozenset({"customers", "orders"}),
        expected_scoped_tables=("orders",),
        expected_limit=100,
        expected_columns=frozenset({"name", "customer_id", "id", "account_id"}),
        sql_markers=("exists",),
    ),
    AcceptedCase(
        name="scoped orders CTE",
        question="Show a summary of my recent orders",
        sql=(
            "WITH scoped_orders AS ("
            "SELECT id, total_cents FROM orders WHERE account_id = @user_id"
            ") SELECT id, total_cents FROM scoped_orders LIMIT 100"
        ),
        expected_tables=frozenset({"orders"}),
        expected_scoped_tables=("orders",),
        expected_limit=100,
        expected_columns=frozenset({"id", "total_cents", "account_id"}),
        sql_markers=("with", "scoped_orders"),
    ),
    AcceptedCase(
        name="scoped UNION ALL",
        question="Combine my order IDs and order-item IDs",
        sql=(
            "SELECT id FROM orders WHERE account_id = @user_id "
            "UNION ALL SELECT id FROM order_items WHERE account_id = @user_id LIMIT 100"
        ),
        expected_tables=frozenset({"orders", "order_items"}),
        expected_scoped_tables=("order_items", "orders"),
        expected_limit=100,
        expected_columns=frozenset({"id", "account_id"}),
        sql_markers=("union all",),
    ),
)


@pytest.mark.parametrize("case", ACCEPTED_CASES, ids=lambda case: case.name)
def test_commerce_pipeline_approves_real_yaml_scenarios(case: AcceptedCase):
    provider = ScenarioProvider(case.provider_response)
    guard = QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)

    result = _run(guard.prepare(case.question))

    assert result.approved is True
    assert result.stage == "approved"
    assert result.generated is not None
    assert result.structural is not None and result.structural.valid is True
    assert result.policy is not None and result.policy.valid is True
    assert set(result.generated.referenced_tables) == case.expected_tables
    assert set(result.structural.referenced_tables) == case.expected_tables
    parsed_column_names = {
        column.rsplit(".", 1)[-1] for column in result.structural.referenced_columns
    }
    assert case.expected_columns <= parsed_column_names
    assert result.policy.scoped_tables == case.expected_scoped_tables
    assert result.policy.detected_parameters == ("user_id",)
    assert result.policy.effective_limit == case.expected_limit
    normalized_sql = result.generated.sql.lower()
    for marker in case.sql_markers:
        assert marker in normalized_sql
    assert len(provider.calls) == 1


def test_parser_metadata_is_authoritative_when_provider_metadata_is_wrong():
    response = {
        "sql": "SELECT id FROM orders WHERE account_id = @user_id LIMIT 20",
        "referenced_tables": ["customers"],
        "referenced_columns": ["name"],
        "explanation": "intentionally mismatched provider metadata",
    }
    provider = ScenarioProvider(response)
    guard = QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)

    result = _run(guard.prepare("Show my latest 20 orders"))

    assert result.approved is True
    assert result.structural is not None
    assert result.structural.referenced_tables == ("orders",)
    parsed_column_names = {
        column.rsplit(".", 1)[-1] for column in result.structural.referenced_columns
    }
    assert parsed_column_names >= {"id", "account_id"}
    assert "Model-reported tables differ from parsed SQL references." in result.structural.warnings
    assert "Model-reported columns differ from parsed SQL references." in result.structural.warnings


@dataclass(frozen=True)
class RejectionCase:
    name: str
    sql: str
    expected_codes: frozenset[str]


STRUCTURAL_REJECTION_CASES = (
    RejectionCase(
        name="unknown table",
        sql="SELECT id FROM payments WHERE account_id = @user_id LIMIT 10",
        expected_codes=frozenset({"TABLE_NOT_ALLOWED"}),
    ),
    RejectionCase(
        name="unknown column",
        sql="SELECT secret_field FROM orders WHERE account_id = @user_id LIMIT 10",
        expected_codes=frozenset({"COLUMN_NOT_ALLOWED"}),
    ),
    RejectionCase(
        name="wildcard projection",
        sql="SELECT * FROM orders WHERE account_id = @user_id LIMIT 10",
        expected_codes=frozenset({"WILDCARD_NOT_ALLOWED"}),
    ),
    RejectionCase(
        name="write statement",
        sql="DELETE FROM orders WHERE account_id = @user_id",
        expected_codes=frozenset({"WRITE_OPERATION"}),
    ),
    RejectionCase(
        name="multiple statements",
        sql="SELECT id FROM orders WHERE account_id = @user_id LIMIT 10; DELETE FROM orders",
        expected_codes=frozenset({"MULTIPLE_STATEMENTS"}),
    ),
    RejectionCase(
        name="system schema access",
        sql="SELECT relname FROM pg_catalog.pg_class LIMIT 10",
        expected_codes=frozenset({"SYSTEM_SCHEMA_ACCESS"}),
    ),
)


@pytest.mark.parametrize("case", STRUCTURAL_REJECTION_CASES, ids=lambda case: case.name)
def test_structural_rejections_stop_before_policy(case: RejectionCase):
    provider = ScenarioProvider({"sql": case.sql})
    guard = QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)
    policy_calls: list[str] = []
    guard._policy_validator.validate = (  # type: ignore[method-assign]
        lambda sql: policy_calls.append(sql)
    )

    result = _run(guard.prepare(case.name))

    assert result.approved is False
    assert result.stage == "structural_validation"
    assert result.generated is not None
    assert result.structural is not None and result.structural.valid is False
    assert result.policy is None
    assert case.expected_codes <= {error.code for error in result.structural.errors}
    assert policy_calls == []


POLICY_REJECTION_CASES = (
    RejectionCase(
        name="missing user scope",
        sql="SELECT id FROM orders LIMIT 10",
        expected_codes=frozenset({"USER_SCOPE_REQUIRED"}),
    ),
    RejectionCase(
        name="literal user scope",
        sql="SELECT id FROM orders WHERE account_id = 'abc' LIMIT 10",
        expected_codes=frozenset({"USER_SCOPE_LITERAL_NOT_ALLOWED"}),
    ),
    RejectionCase(
        name="wrong scope parameter",
        sql="SELECT id FROM orders WHERE account_id = @other_id LIMIT 10",
        expected_codes=frozenset({"USER_SCOPE_PARAMETER_REQUIRED"}),
    ),
    RejectionCase(
        name="unsafe OR scope",
        sql=("SELECT id FROM orders WHERE account_id = @user_id OR status = 'public' LIMIT 10"),
        expected_codes=frozenset({"USER_SCOPE_AMBIGUOUS"}),
    ),
    RejectionCase(
        name="missing result limit",
        sql="SELECT id FROM orders WHERE account_id = @user_id",
        expected_codes=frozenset({"RESULT_LIMIT_REQUIRED"}),
    ),
    RejectionCase(
        name="result limit too high",
        sql="SELECT id FROM orders WHERE account_id = @user_id LIMIT 501",
        expected_codes=frozenset({"RESULT_LIMIT_TOO_HIGH"}),
    ),
    RejectionCase(
        name="unscoped nested subquery",
        sql=(
            "SELECT c.name FROM customers c WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id = c.id) LIMIT 100"
        ),
        expected_codes=frozenset({"USER_SCOPE_REQUIRED"}),
    ),
    RejectionCase(
        name="one joined table missing scope",
        sql=(
            "SELECT o.id, i.product_name FROM orders o "
            "JOIN order_items i ON i.order_id = o.id "
            "WHERE o.account_id = @user_id LIMIT 100"
        ),
        expected_codes=frozenset({"USER_SCOPE_REQUIRED"}),
    ),
    RejectionCase(
        name="branch-local limit without final limit",
        sql=(
            "SELECT id FROM orders WHERE account_id = @user_id LIMIT 10 "
            "UNION ALL SELECT id FROM order_items WHERE account_id = @user_id"
        ),
        expected_codes=frozenset({"RESULT_LIMIT_REQUIRED"}),
    ),
)


@pytest.mark.parametrize("case", POLICY_REJECTION_CASES, ids=lambda case: case.name)
def test_policy_rejections_preserve_structural_result(case: RejectionCase):
    provider = ScenarioProvider({"sql": case.sql})
    guard = QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)

    result = _run(guard.prepare(case.name))

    assert result.approved is False
    assert result.stage == "policy_validation"
    assert result.generated is not None
    assert result.structural is not None and result.structural.valid is True
    assert result.policy is not None and result.policy.valid is False
    assert case.expected_codes <= {error.code for error in result.policy.errors}


@pytest.mark.parametrize(
    ("response", "question"),
    [
        ("not JSON", "malformed provider response"),
        (RuntimeError("provider unavailable"), "provider exception"),
    ],
    ids=("malformed-json", "provider-exception"),
)
def test_generation_failures_stop_before_both_validators(response: object, question: str):
    provider = ScenarioProvider(response)
    guard = QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)
    structural_calls: list[object] = []
    policy_calls: list[object] = []
    guard._structural_validator.validate = (  # type: ignore[method-assign]
        lambda value: structural_calls.append(value)
    )
    guard._policy_validator.validate = (  # type: ignore[method-assign]
        lambda value: policy_calls.append(value)
    )

    result = _run(guard.prepare(question))

    assert result.approved is False
    assert result.stage == "generation"
    assert result.generated is None
    assert result.structural is None
    assert result.policy is None
    assert structural_calls == []
    assert policy_calls == []


def test_conversation_history_reaches_provider_without_mutation():
    history = (
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    )
    original_history = copy.deepcopy(history)
    provider = ScenarioProvider(ACCEPTED_CASES[0].provider_response)
    guard = QueryGuard.from_yaml(EXAMPLE_PATH, provider=provider)

    result = _run(
        guard.prepare(
            ACCEPTED_CASES[0].question,
            conversation_history=history,
        )
    )

    assert result.approved is True
    assert provider.calls[0][1:-1] == history
    assert provider.calls[0][1] is not history[0]
    assert history == original_history


def _run(awaitable):
    """Run one async facade call without adding an async test plugin."""

    import asyncio

    return asyncio.run(awaitable)
