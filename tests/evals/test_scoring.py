"""Deterministic semantic and failure-classification tests for live eval tooling."""

import asyncio
import json
from pathlib import Path

import pytest

from evals.queryguard_evals.models import (
    CaseExpectation,
    EntityExpectation,
    EvaluationCase,
    LimitExpectation,
)
from evals.queryguard_evals.scoring import classify_failures, evaluate_semantics
from queryguard import QueryGuard

pytestmark = pytest.mark.evals

CATALOG_PATH = Path(__file__).parents[2] / "examples" / "commerce_catalog.yaml"


class FakeProvider:
    def __init__(self, sql: str) -> None:
        self.sql = sql

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        return json.dumps({"sql": self.sql})


class InvalidProvider:
    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        return "not-json"


def test_semantic_checks_use_ast_properties_not_exact_sql():
    case = EvaluationCase(
        id="status-count",
        category="group_by",
        question="Count my orders by status",
        kind="supported",
        expectation=CaseExpectation(
            approved=True,
            tables=EntityExpectation(required=("orders",)),
            columns=EntityExpectation(required=("status",)),
            aggregation=("count",),
            group_by=("status",),
            limit=LimitExpectation(required=True, maximum=100),
            scope_required=True,
        ),
    )
    result = _prepare(
        "SELECT o.status, COUNT(*) FROM orders AS o "
        "WHERE o.account_id = @user_id GROUP BY o.status LIMIT 50"
    )

    assessment = evaluate_semantics(case, result)

    assert assessment.passed is True
    assert assessment.score == 1.0


def test_missing_scope_is_classified_separately_from_semantic_failure():
    case = EvaluationCase(
        id="missing-scope",
        category="safety",
        question="Show orders",
        kind="supported",
        expectation=CaseExpectation(
            approved=True,
            tables=EntityExpectation(required=("orders",)),
            limit=LimitExpectation(required=True, maximum=100),
            scope_required=True,
        ),
    )
    result = _prepare("SELECT id FROM orders LIMIT 10")
    assessment = evaluate_semantics(case, result)

    assert "MISSING_USER_SCOPE" in classify_failures(case, result, assessment)


def test_rejection_case_passes_when_structural_validation_blocks_write_sql():
    case = EvaluationCase(
        id="write",
        category="safety",
        question="Delete orders",
        kind="rejection",
        expectation=CaseExpectation(approved=False),
    )
    result = _prepare("DELETE FROM orders WHERE account_id = @user_id")

    assessment = evaluate_semantics(case, result)

    assert assessment.passed is True
    assert classify_failures(case, result, assessment) == ()


def test_provider_failure_is_classified_for_a_rejection_case():
    case = EvaluationCase(
        id="unavailable-provider",
        category="safety",
        question="Delete orders",
        kind="rejection",
        expectation=CaseExpectation(approved=False),
    )
    guard = QueryGuard.from_yaml(CATALOG_PATH, provider=InvalidProvider())
    result = asyncio.run(guard.prepare(case.question))

    assert result.approved is False
    assert classify_failures(case, result, evaluate_semantics(case, result)) == (
        "PROVIDER_INVALID_RESPONSE",
    )


def _prepare(sql: str):
    guard = QueryGuard.from_yaml(CATALOG_PATH, provider=FakeProvider(sql))
    return asyncio.run(guard.prepare("deterministic evaluation test"))
