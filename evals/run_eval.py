"""Run opt-in live Ollama evaluations without involving pytest or normal CI."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parent
if str(EVALS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT.parent))

from evals.queryguard_evals.cases import load_cases
from evals.queryguard_evals.models import EvaluationSettings
from evals.queryguard_evals.ollama_provider import OllamaProvider
from evals.queryguard_evals.reporting import write_reports
from evals.queryguard_evals.runner import run_evaluation


def parse_arguments() -> argparse.Namespace:
    """Parse an explicit, repeatable local evaluation invocation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Locally installed Ollama model name")
    parser.add_argument(
        "--cases",
        type=Path,
        default=EVALS_ROOT / "cases" / "commerce.yaml",
        help="YAML evaluation case file",
    )
    parser.add_argument("--category", action="append", help="Restrict to one or more categories")
    parser.add_argument(
        "--safety-only", action="store_true", help="Run only cases that expect a safe rejection"
    )
    parser.add_argument("--limit", type=int, help="Limit the number of selected cases")
    parser.add_argument(
        "--output",
        type=Path,
        default=EVALS_ROOT / "results" / "latest",
        help="Output prefix; .json and .md are appended",
    )
    parser.add_argument("--temperature", type=float, default=0.0, help="Ollama temperature")
    parser.add_argument("--runs-per-case", type=int, default=1, help="Repeats per selected case")
    parser.add_argument(
        "--timeout-seconds", type=float, default=120.0, help="Per-request Ollama timeout"
    )
    return parser.parse_args()


async def main() -> int:
    """Execute selected cases and write both report formats."""

    arguments = parse_arguments()
    if arguments.limit is not None and arguments.limit < 1:
        raise SystemExit("--limit must be positive")
    if arguments.runs_per_case < 1:
        raise SystemExit("--runs-per-case must be positive")
    cases = load_cases(arguments.cases)
    if arguments.category:
        categories = set(arguments.category)
        cases = tuple(case for case in cases if case.category in categories)
    if arguments.safety_only:
        cases = tuple(case for case in cases if case.kind == "rejection")
    if arguments.limit is not None:
        cases = cases[: arguments.limit]
    if not cases:
        raise SystemExit("No evaluation cases selected")

    settings = EvaluationSettings(
        model=arguments.model,
        temperature=arguments.temperature,
        runs_per_case=arguments.runs_per_case,
        timeout_seconds=arguments.timeout_seconds,
    )
    provider = OllamaProvider(
        arguments.model,
        temperature=arguments.temperature,
        timeout_seconds=arguments.timeout_seconds,
    )
    run = await run_evaluation(
        cases,
        catalog_path=EVALS_ROOT.parent / "examples" / "commerce_catalog.yaml",
        provider=provider,
        settings=settings,
    )
    json_path, markdown_path = write_reports(arguments.output, run)
    summary = run.summary
    print(f"Wrote {json_path} and {markdown_path}")
    print(
        " | ".join(
            (
                f"generation={summary.generation_success_rate * 100:.1f}%",
                f"structural={_percent(summary.structural_validity_rate)}",
                f"policy={_percent(summary.policy_validity_rate)}",
                f"semantic={_percent(summary.semantic_correctness_rate)}",
                f"unsafe_rejection={_percent(summary.unsafe_request_rejection_rate)}",
            )
        )
    )
    return 0


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
