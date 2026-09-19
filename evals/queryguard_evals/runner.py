"""Run evaluation cases through the public QueryGuard facade pipeline."""

from __future__ import annotations

import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from evals.queryguard_evals.models import (
    CategorySummary,
    EvaluationCase,
    EvaluationRecord,
    EvaluationRun,
    EvaluationSettings,
    EvaluationSummary,
)
from evals.queryguard_evals.scoring import classify_failures, evaluate_semantics, percentile_95
from queryguard import QueryGuard
from queryguard.generation import SqlGenerationProvider


async def run_evaluation(
    cases: tuple[EvaluationCase, ...],
    *,
    catalog_path: str | Path,
    provider: SqlGenerationProvider,
    settings: EvaluationSettings,
) -> EvaluationRun:
    """Evaluate all selected cases using ``QueryGuard.from_yaml(...).prepare(...)``."""

    if not cases:
        raise ValueError("at least one evaluation case is required")
    guard = QueryGuard.from_yaml(catalog_path, provider=provider)
    started_at = datetime.now(UTC).isoformat()
    run_started = time.perf_counter()
    records: list[EvaluationRecord] = []
    for case in cases:
        for run_index in range(1, settings.runs_per_case + 1):
            records.append(await _run_case(guard, case, provider, settings.model, run_index))
    total_duration_ms = (time.perf_counter() - run_started) * 1000
    record_tuple = tuple(records)
    return EvaluationRun(
        started_at=started_at,
        settings=settings,
        total_duration_ms=total_duration_ms,
        records=record_tuple,
        summary=summarize_records(record_tuple),
    )


async def _run_case(
    guard: QueryGuard,
    case: EvaluationCase,
    provider: SqlGenerationProvider,
    model: str,
    run_index: int,
) -> EvaluationRecord:
    started_at = time.perf_counter()
    result = await guard.prepare(case.question)
    duration_ms = (time.perf_counter() - started_at) * 1000
    assessment = evaluate_semantics(case, result)
    structural = result.structural
    policy = result.policy
    provider_duration = getattr(provider, "last_duration_ms", None)
    if not isinstance(provider_duration, float):
        provider_duration = None
    generation_error = result.errors[0] if result.stage == "generation" and result.errors else None
    structural_valid = structural is not None and structural.valid
    policy_valid = policy is not None and policy.valid
    if case.kind == "supported":
        overall_pass = bool(
            result.generated is not None and structural_valid and policy_valid and assessment.passed
        )
    else:
        overall_pass = not result.approved
    return EvaluationRecord(
        case_id=case.id,
        category=case.category,
        kind=case.kind,
        question=case.question,
        run_index=run_index,
        model=model,
        duration_ms=duration_ms,
        provider_duration_ms=provider_duration,
        generation_success=result.generated is not None,
        generated_sql=result.generated.sql if result.generated else None,
        generation_error=generation_error,
        structural_valid=structural_valid,
        structural_error_codes=tuple(error.code for error in structural.errors)
        if structural
        else (),
        policy_valid=policy_valid,
        policy_error_codes=tuple(error.code for error in policy.errors) if policy else (),
        approved=result.approved,
        detected_tables=structural.referenced_tables if structural else (),
        detected_columns=structural.referenced_columns if structural else (),
        scoped_tables=policy.scoped_tables if policy else (),
        effective_limit=policy.effective_limit if policy else None,
        semantic_checks=assessment.checks,
        semantic_score=assessment.score,
        overall_pass=overall_pass,
        failure_classifications=classify_failures(case, result, assessment),
    )


def summarize_records(records: tuple[EvaluationRecord, ...]) -> EvaluationSummary:
    """Compute rates with supported and safety/rejection cases kept distinct."""

    supported = [record for record in records if record.kind == "supported"]
    safety = [record for record in records if record.kind == "rejection"]
    provider_latencies: list[float] = [
        record.provider_duration_ms for record in records if record.provider_duration_ms is not None
    ]
    prepare_latencies = [record.duration_ms for record in records]
    failure_counts = Counter(
        classification for record in records for classification in record.failure_classifications
    )
    return EvaluationSummary(
        total_cases=len(records),
        supported_cases=len(supported),
        safety_cases=len(safety),
        generation_success_rate=_rate(record.generation_success for record in records),
        structural_validity_rate=_rate_or_none(record.structural_valid for record in supported),
        policy_validity_rate=_rate_or_none(record.policy_valid for record in supported),
        approval_rate=_rate_or_none(record.approved for record in supported),
        semantic_correctness_rate=_rate_or_none(
            bool(record.semantic_checks) and all(record.semantic_checks.values())
            for record in supported
        ),
        unsafe_request_rejection_rate=_rate_or_none(not record.approved for record in safety),
        provider_latency_mean_ms=_mean_or_none(provider_latencies),
        provider_latency_median_ms=_median_or_none(provider_latencies),
        provider_latency_p95_ms=percentile_95(provider_latencies),
        prepare_latency_mean_ms=_mean_or_none(prepare_latencies) or 0.0,
        prepare_latency_median_ms=_median_or_none(prepare_latencies) or 0.0,
        prepare_latency_p95_ms=percentile_95(prepare_latencies) or 0.0,
        category_summaries=_category_summaries(records),
        failure_counts=dict(sorted(failure_counts.items())),
    )


def _category_summaries(records: tuple[EvaluationRecord, ...]) -> dict[str, CategorySummary]:
    grouped: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.category].append(record)
    return {
        category: CategorySummary(
            cases=len(category_records),
            passed=sum(record.overall_pass for record in category_records),
            semantic_passed=sum(
                bool(record.semantic_checks) and all(record.semantic_checks.values())
                for record in category_records
            ),
            structural_valid=sum(record.structural_valid for record in category_records),
            policy_valid=sum(record.policy_valid for record in category_records),
        )
        for category, category_records in sorted(grouped.items())
    }


def _rate(values: Iterable[bool]) -> float:
    evaluated = list(values)
    return sum(evaluated) / len(evaluated) if evaluated else 0.0


def _rate_or_none(values: Iterable[bool]) -> float | None:
    evaluated = list(values)
    return sum(evaluated) / len(evaluated) if evaluated else None


def _mean_or_none(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None
