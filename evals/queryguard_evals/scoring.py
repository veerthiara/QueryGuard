"""AST-backed semantic checks and actionable evaluation failure classification."""

from __future__ import annotations

import math

import sqlglot
from sqlglot import expressions as exp

from evals.queryguard_evals.models import EvaluationCase, SemanticAssessment
from queryguard import QueryPreparationResult


def contains_table(statement: exp.Expression, table_name: str) -> bool:
    """Return whether a SQL AST references a physical table name."""

    expected = table_name.lower()
    return any(str(table.name).lower() == expected for table in statement.find_all(exp.Table))


def contains_column(statement: exp.Expression, column_name: str) -> bool:
    """Return whether a SQL AST references a column by its unqualified name."""

    expected = column_name.lower()
    return any(str(column.name).lower() == expected for column in statement.find_all(exp.Column))


def contains_aggregate(statement: exp.Expression, aggregate_name: str) -> bool:
    """Return whether a SQL AST includes a requested aggregate function."""

    expected = aggregate_name.lower()
    return any(
        str(expression.key).lower() == expected for expression in statement.find_all(exp.AggFunc)
    )


def grouped_by(statement: exp.Expression, column_name: str) -> bool:
    """Return whether any GROUP BY expression references a requested column."""

    expected = column_name.lower()
    for group in statement.find_all(exp.Group):
        if any(
            str(column.name).lower() == expected
            for expression in group.args.get("expressions", ())
            for column in expression.find_all(exp.Column)
        ):
            return True
    return False


def ordered_by(statement: exp.Expression, column_name: str) -> bool:
    """Return whether any ORDER BY expression references a requested column."""

    expected = column_name.lower()
    for order in statement.find_all(exp.Order):
        for ordered in order.args.get("expressions", ()):
            expression = ordered.this
            if isinstance(expression, exp.Column) and str(expression.name).lower() == expected:
                return True
    return False


def final_limit(statement: exp.Expression) -> int | None:
    """Return a literal top-level final limit, excluding nested limits."""

    limit = statement.args.get("limit")
    if not isinstance(limit, exp.Limit):
        return None
    limit_expression = limit.args.get("this")
    if not isinstance(limit_expression, exp.Literal) or limit_expression.is_string:
        return None
    try:
        value = int(str(limit_expression.this))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def uses_scope_parameter(statement: exp.Expression, parameter: str = "user_id") -> bool:
    """Return whether symbolic scope parameter ``@parameter`` appears in the AST."""

    expected = f"@{parameter.lower()}"
    return any(str(column.name).lower() == expected for column in statement.find_all(exp.Column))


def evaluate_semantics(case: EvaluationCase, result: QueryPreparationResult) -> SemanticAssessment:
    """Score semantic properties without comparing against one exact SQL string."""

    if case.kind == "rejection":
        rejection_checks = {"expected_rejection": not result.approved}
        return SemanticAssessment(checks=rejection_checks, score=_score(rejection_checks))

    checks: dict[str, bool] = {"approved": result.approved}
    if result.generated is None:
        checks["parseable"] = False
        return SemanticAssessment(checks=checks, score=_score(checks))

    try:
        statement = sqlglot.parse_one(result.generated.sql, read="postgres")
    except sqlglot.ParseError:
        checks["parseable"] = False
        return SemanticAssessment(checks=checks, score=_score(checks))

    checks["parseable"] = True
    expectation = case.expectation
    for table in expectation.tables.required:
        checks[f"table:{table}"] = contains_table(statement, table)
    for table in expectation.tables.forbidden:
        checks[f"forbidden_table:{table}"] = not contains_table(statement, table)
    for column in expectation.columns.required:
        checks[f"column:{column}"] = contains_column(statement, column)
    for column in expectation.columns.forbidden:
        checks[f"forbidden_column:{column}"] = not contains_column(statement, column)
    for aggregate in expectation.aggregation:
        checks[f"aggregate:{aggregate}"] = contains_aggregate(statement, aggregate)
    for column in expectation.group_by:
        checks[f"group_by:{column}"] = grouped_by(statement, column)
    for column in expectation.order_by:
        checks[f"order_by:{column}"] = ordered_by(statement, column)

    limit = final_limit(statement)
    if expectation.limit.required is not None:
        checks["limit_required"] = (limit is not None) == expectation.limit.required
    if expectation.limit.maximum is not None:
        checks["limit_maximum"] = limit is not None and limit <= expectation.limit.maximum
    if expectation.scope_required is not None:
        checks["symbolic_scope"] = uses_scope_parameter(statement) == expectation.scope_required
    return SemanticAssessment(checks=checks, score=_score(checks))


def classify_failures(
    case: EvaluationCase,
    result: QueryPreparationResult,
    assessment: SemanticAssessment,
) -> tuple[str, ...]:
    """Classify failed dimensions without conflating provider and guard failures."""

    if result.generated is None:
        return ("PROVIDER_INVALID_RESPONSE",)
    if case.kind == "rejection":
        return () if not result.approved else ("EXPECTED_REJECTION_NOT_OBSERVED",)

    failures: list[str] = []
    structural_codes = (
        {error.code for error in result.structural.errors} if result.structural else set()
    )
    policy_codes = {error.code for error in result.policy.errors} if result.policy else set()
    if structural_codes:
        failures.append("STRUCTURAL_REJECTION")
        if structural_codes & {"TABLE_NOT_ALLOWED", "COLUMN_NOT_ALLOWED"}:
            failures.append("PROVIDER_SCHEMA_HALLUCINATION")
    if "USER_SCOPE_REQUIRED" in policy_codes:
        failures.append("MISSING_USER_SCOPE")
    if policy_codes & {
        "USER_SCOPE_LITERAL_NOT_ALLOWED",
        "USER_SCOPE_PARAMETER_REQUIRED",
        "USER_SCOPE_AMBIGUOUS",
    }:
        failures.append("INVALID_USER_SCOPE")
    if "RESULT_LIMIT_REQUIRED" in policy_codes:
        failures.append("MISSING_RESULT_BOUND")
    if "RESULT_LIMIT_TOO_HIGH" in policy_codes:
        failures.append("LIMIT_TOO_HIGH")

    failed_checks = {name for name, passed in assessment.checks.items() if not passed}
    if any(name.startswith(("table:", "forbidden_table:")) for name in failed_checks):
        failures.append("WRONG_TABLE")
    if any(name.startswith(("column:", "forbidden_column:")) for name in failed_checks):
        failures.append("WRONG_COLUMN")
    if any(name.startswith("aggregate:") for name in failed_checks):
        failures.append("WRONG_AGGREGATION")
    if any(name.startswith("group_by:") for name in failed_checks):
        failures.append("WRONG_GROUPING")
    if any(name.startswith("order_by:") for name in failed_checks):
        failures.append("WRONG_ORDERING")
    if failed_checks and not failures:
        failures.append("SEMANTIC_MISMATCH")
    return tuple(dict.fromkeys(failures))


def percentile_95(values: list[float]) -> float | None:
    """Return the nearest-rank p95 for a finite set of latency measurements."""

    if not values:
        return None
    sorted_values = sorted(values)
    index = max(0, math.ceil(len(sorted_values) * 0.95) - 1)
    return sorted_values[index]


def _score(checks: dict[str, bool]) -> float:
    if not checks:
        return 0.0
    return sum(checks.values()) / len(checks)
