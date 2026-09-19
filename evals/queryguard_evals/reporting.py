"""Machine-readable and concise Markdown reporting for evaluation runs."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from evals.queryguard_evals.models import CategorySummary, EvaluationRecord, EvaluationRun


def write_reports(output_prefix: str | Path, run: EvaluationRun) -> tuple[Path, Path]:
    """Write one JSON payload and one human-readable Markdown summary."""

    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    markdown_path = prefix.with_suffix(".md")
    json_path.write_text(json.dumps(asdict(run), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(run), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(run: EvaluationRun) -> str:
    """Render aggregate outcomes without dumping prompts or all raw model output."""

    summary = run.summary
    lines = [
        "# QueryGuard live evaluation report",
        "",
        f"- Model: `{run.settings.model}`",
        f"- Started (UTC): `{run.started_at}`",
        f"- Cases: {summary.total_cases} ({summary.supported_cases} supported, {summary.safety_cases} safety)",
        f"- Temperature: {run.settings.temperature}",
        f"- Runs per case: {run.settings.runs_per_case}",
        f"- Total duration: {run.total_duration_ms:.1f} ms",
        "",
        "## Metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Generation success | {_percent(summary.generation_success_rate)} |",
        f"| Structural validity (supported) | {_percent(summary.structural_validity_rate)} |",
        f"| Policy validity (supported) | {_percent(summary.policy_validity_rate)} |",
        f"| Approval (supported) | {_percent(summary.approval_rate)} |",
        f"| Semantic correctness (supported) | {_percent(summary.semantic_correctness_rate)} |",
        f"| Unsafe-request rejection | {_percent(summary.unsafe_request_rejection_rate)} |",
        f"| Provider latency mean / median / p95 | {_latencies(summary.provider_latency_mean_ms, summary.provider_latency_median_ms, summary.provider_latency_p95_ms)} |",
        f"| Prepare latency mean / median / p95 | {_latencies(summary.prepare_latency_mean_ms, summary.prepare_latency_median_ms, summary.prepare_latency_p95_ms)} |",
        "",
        "## By category",
        "",
        "| Category | Cases | Passed | Semantic | Structural | Policy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category, aggregate in summary.category_summaries.items():
        lines.append(
            f"| {category} | {aggregate.cases} | {aggregate.passed} | "
            f"{aggregate.semantic_passed} | {aggregate.structural_valid} | {aggregate.policy_valid} |"
        )
    lines.extend(["", "## Lowest overall-pass categories", ""])
    for category, aggregate in _lowest_categories(summary.category_summaries):
        lines.append(f"- `{category}`: {aggregate.passed}/{aggregate.cases} overall passes")
    lines.extend(["", "## Failure classifications", ""])
    if summary.failure_counts:
        lines.extend(["| Classification | Count |", "|---|---:|"])
        lines.extend(f"| {name} | {count} |" for name, count in summary.failure_counts.items())
    else:
        lines.append("No failures classified.")
    failures = [record for record in run.records if record.failure_classifications]
    lines.extend(["", "## Representative failures", ""])
    if failures:
        for record in failures[:5]:
            lines.extend(_failure_lines(record))
    else:
        lines.append("No representative failures.")
    return "\n".join(lines) + "\n"


def _failure_lines(record: EvaluationRecord) -> list[str]:
    sql = _truncate(record.generated_sql or record.generation_error or "No generated SQL", 180)
    return [
        f"### `{record.case_id}` — {', '.join(record.failure_classifications)}",
        "",
        f"Question: {record.question}",
        "",
        f"Candidate: `{sql}`",
        "",
    ]


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _latencies(mean: float | None, median: float | None, p95: float | None) -> str:
    if mean is None or median is None or p95 is None:
        return "n/a"
    return f"{mean:.1f} / {median:.1f} / {p95:.1f} ms"


def _lowest_categories(
    category_summaries: dict[str, CategorySummary],
) -> list[tuple[str, CategorySummary]]:
    """Return the five weakest categories without depending on report input order."""

    return sorted(
        category_summaries.items(),
        key=lambda item: (item[1].passed / item[1].cases, item[0]),
    )[:5]


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"
