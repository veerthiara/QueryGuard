"""Deterministic tests for evaluation-case YAML loading."""

from pathlib import Path

import pytest

from evals.queryguard_evals.cases import CaseLoadError, load_cases

pytestmark = pytest.mark.evals

CASE_PATH = Path(__file__).parents[2] / "evals" / "cases" / "commerce.yaml"


def test_commerce_dataset_is_large_and_has_a_dedicated_safety_subset():
    cases = load_cases(CASE_PATH)

    assert len(cases) >= 50
    assert sum(case.kind == "rejection" for case in cases) >= 15
    assert {"joins", "CTE", "nested_subquery", "UNION", "UNION_ALL"} <= {
        case.category for case in cases
    }


def test_case_loader_rejects_invalid_root(tmp_path: Path):
    path = tmp_path / "invalid.yaml"
    path.write_text("cases: []\n", encoding="utf-8")

    with pytest.raises(CaseLoadError, match="non-empty"):
        load_cases(path)


def test_case_loader_rejects_duplicate_identifiers(tmp_path: Path):
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        """
cases:
  - id: duplicate
    category: test
    question: One
    kind: rejection
    expect: {approved: false}
  - id: duplicate
    category: test
    question: Two
    kind: rejection
    expect: {approved: false}
""",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unique"):
        load_cases(path)
