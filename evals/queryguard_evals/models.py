"""Data contracts owned by the evaluation harness, not the QueryGuard package."""

from dataclasses import dataclass, field
from typing import Literal

EvaluationKind = Literal["supported", "rejection"]


@dataclass(frozen=True)
class EntityExpectation:
    """Required and forbidden table or column names for one evaluation case."""

    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class LimitExpectation:
    """Expected final result-limit behavior for one evaluation case."""

    required: bool | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class CaseExpectation:
    """Semantic and pipeline properties that may be asserted without exact SQL."""

    approved: bool
    tables: EntityExpectation = EntityExpectation()
    columns: EntityExpectation = EntityExpectation()
    aggregation: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    order_by: tuple[str, ...] = ()
    limit: LimitExpectation = LimitExpectation()
    scope_required: bool | None = None


@dataclass(frozen=True)
class EvaluationCase:
    """One reusable natural-language SQL evaluation case."""

    id: str
    category: str
    question: str
    kind: EvaluationKind
    expectation: CaseExpectation


@dataclass(frozen=True)
class SemanticAssessment:
    """Property-level semantic result for one generated candidate."""

    checks: dict[str, bool]
    score: float

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


@dataclass(frozen=True)
class EvaluationSettings:
    """Replayable settings recorded alongside a live evaluation report."""

    model: str
    temperature: float
    runs_per_case: int
    timeout_seconds: float


@dataclass(frozen=True)
class EvaluationRecord:
    """One complete facade-pipeline evaluation result."""

    case_id: str
    category: str
    kind: EvaluationKind
    question: str
    run_index: int
    model: str
    duration_ms: float
    provider_duration_ms: float | None
    generation_success: bool
    generated_sql: str | None
    generation_error: str | None
    structural_valid: bool
    structural_error_codes: tuple[str, ...]
    policy_valid: bool
    policy_error_codes: tuple[str, ...]
    approved: bool
    detected_tables: tuple[str, ...]
    detected_columns: tuple[str, ...]
    scoped_tables: tuple[str, ...]
    effective_limit: int | None
    semantic_checks: dict[str, bool]
    semantic_score: float
    overall_pass: bool
    failure_classifications: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategorySummary:
    """Aggregate scores for one dataset category."""

    cases: int
    passed: int
    semantic_passed: int
    structural_valid: int
    policy_valid: int


@dataclass(frozen=True)
class EvaluationSummary:
    """Top-level metrics intentionally kept separate for diagnosis."""

    total_cases: int
    supported_cases: int
    safety_cases: int
    generation_success_rate: float
    structural_validity_rate: float | None
    policy_validity_rate: float | None
    approval_rate: float | None
    semantic_correctness_rate: float | None
    unsafe_request_rejection_rate: float | None
    provider_latency_mean_ms: float | None
    provider_latency_median_ms: float | None
    provider_latency_p95_ms: float | None
    prepare_latency_mean_ms: float
    prepare_latency_median_ms: float
    prepare_latency_p95_ms: float
    category_summaries: dict[str, CategorySummary] = field(default_factory=dict)
    failure_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationRun:
    """Serializable report payload for one model and selected set of cases."""

    started_at: str
    settings: EvaluationSettings
    total_duration_ms: float
    records: tuple[EvaluationRecord, ...]
    summary: EvaluationSummary
