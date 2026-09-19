"""Deterministic facade execution and report aggregation tests for evaluation tooling."""

import asyncio
import json
from pathlib import Path

import pytest

from evals.queryguard_evals.models import CaseExpectation, EvaluationCase, EvaluationSettings
from evals.queryguard_evals.reporting import render_markdown, write_reports
from evals.queryguard_evals.runner import run_evaluation

pytestmark = pytest.mark.evals

CATALOG_PATH = Path(__file__).parents[2] / "examples" / "commerce_catalog.yaml"


class ScenarioProvider:
    last_duration_ms = 4.0

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        question = messages[-1]["content"]
        sql = (
            "DELETE FROM orders WHERE account_id = @user_id"
            if question == "Unsafe request"
            else "SELECT id FROM orders WHERE account_id = @user_id LIMIT 10"
        )
        return json.dumps({"sql": sql})


def test_runner_uses_facade_for_supported_and_rejection_cases(tmp_path: Path):
    cases = (
        EvaluationCase(
            id="supported",
            category="basic_selection",
            question="Supported request",
            kind="supported",
            expectation=CaseExpectation(approved=True),
        ),
        EvaluationCase(
            id="unsafe",
            category="safety",
            question="Unsafe request",
            kind="rejection",
            expectation=CaseExpectation(approved=False),
        ),
    )
    run = asyncio.run(
        run_evaluation(
            cases,
            catalog_path=CATALOG_PATH,
            provider=ScenarioProvider(),
            settings=EvaluationSettings(
                model="fake", temperature=0.0, runs_per_case=1, timeout_seconds=1.0
            ),
        )
    )

    assert run.summary.total_cases == 2
    assert run.summary.unsafe_request_rejection_rate == 1.0
    assert all(record.overall_pass for record in run.records)
    assert run.records[0].detected_tables == ("orders",)

    json_path, markdown_path = write_reports(tmp_path / "latest", run)
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert "| Category | Cases | Passed | Semantic | Structural | Policy |" in render_markdown(run)
    assert "## Lowest overall-pass categories" in render_markdown(run)
