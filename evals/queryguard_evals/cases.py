"""Strict YAML loader for reusable live-evaluation cases."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml

from evals.queryguard_evals.models import (
    CaseExpectation,
    EntityExpectation,
    EvaluationCase,
    EvaluationKind,
    LimitExpectation,
)


class CaseLoadError(ValueError):
    """Raised when an evaluation case file is malformed."""


def load_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    """Load a strict, reusable set of evaluation cases from YAML."""

    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        raise CaseLoadError(f"unable to load evaluation cases: {path!s}") from exc
    if not isinstance(document, Mapping):
        raise CaseLoadError("evaluation case file root must be a mapping")
    if set(document) != {"cases"}:
        raise CaseLoadError("evaluation case file must contain only a 'cases' key")
    raw_cases = document["cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CaseLoadError("evaluation cases must be a non-empty list")

    cases = tuple(_parse_case(raw_case, index) for index, raw_case in enumerate(raw_cases))
    identifiers = [case.id for case in cases]
    if len(identifiers) != len(set(identifiers)):
        raise CaseLoadError("evaluation case ids must be unique")
    return cases


def _parse_case(raw_case: object, index: int) -> EvaluationCase:
    case = _mapping(raw_case, f"cases[{index}]")
    allowed = {"id", "category", "question", "kind", "expect"}
    if set(case) != allowed:
        raise CaseLoadError(f"cases[{index}] must contain exactly: {', '.join(sorted(allowed))}")
    identifier = _string(case["id"], f"cases[{index}].id")
    category = _string(case["category"], f"cases[{index}].category")
    question = _string(case["question"], f"cases[{index}].question")
    kind = _string(case["kind"], f"cases[{index}].kind")
    if kind not in {"supported", "rejection"}:
        raise CaseLoadError(f"cases[{index}].kind must be 'supported' or 'rejection'")
    return EvaluationCase(
        id=identifier,
        category=category,
        question=question,
        kind=cast("EvaluationKind", kind),
        expectation=_parse_expectation(case["expect"], index),
    )


def _parse_expectation(raw_expectation: object, index: int) -> CaseExpectation:
    expectation = _mapping(raw_expectation, f"cases[{index}].expect")
    allowed = {
        "approved",
        "tables",
        "columns",
        "aggregation",
        "group_by",
        "order_by",
        "limit",
        "scope",
    }
    unknown = set(expectation) - allowed
    if unknown or "approved" not in expectation:
        raise CaseLoadError(f"cases[{index}].expect has invalid keys")
    approved = expectation["approved"]
    if not isinstance(approved, bool):
        raise CaseLoadError(f"cases[{index}].expect.approved must be boolean")
    scope = expectation.get("scope")
    scope_required: bool | None = None
    if scope is not None:
        scope_mapping = _mapping(scope, f"cases[{index}].expect.scope")
        if set(scope_mapping) != {"required"} or not isinstance(scope_mapping["required"], bool):
            raise CaseLoadError(f"cases[{index}].expect.scope must contain boolean 'required'")
        scope_required = scope_mapping["required"]
    return CaseExpectation(
        approved=approved,
        tables=_parse_entities(expectation.get("tables"), index, "tables"),
        columns=_parse_entities(expectation.get("columns"), index, "columns"),
        aggregation=_string_tuple(expectation.get("aggregation"), index, "aggregation"),
        group_by=_string_tuple(expectation.get("group_by"), index, "group_by"),
        order_by=_string_tuple(expectation.get("order_by"), index, "order_by"),
        limit=_parse_limit(expectation.get("limit"), index),
        scope_required=scope_required,
    )


def _parse_entities(raw_value: object, index: int, name: str) -> EntityExpectation:
    if raw_value is None:
        return EntityExpectation()
    value = _mapping(raw_value, f"cases[{index}].expect.{name}")
    unknown = set(value) - {"required", "forbidden"}
    if unknown:
        raise CaseLoadError(f"cases[{index}].expect.{name} has invalid keys")
    return EntityExpectation(
        required=_string_tuple(value.get("required"), index, f"{name}.required"),
        forbidden=_string_tuple(value.get("forbidden"), index, f"{name}.forbidden"),
    )


def _parse_limit(raw_value: object, index: int) -> LimitExpectation:
    if raw_value is None:
        return LimitExpectation()
    value = _mapping(raw_value, f"cases[{index}].expect.limit")
    unknown = set(value) - {"required", "max"}
    if unknown:
        raise CaseLoadError(f"cases[{index}].expect.limit has invalid keys")
    required = value.get("required")
    maximum = value.get("max")
    if required is not None and not isinstance(required, bool):
        raise CaseLoadError(f"cases[{index}].expect.limit.required must be boolean")
    if maximum is not None and (not isinstance(maximum, int) or maximum < 1):
        raise CaseLoadError(f"cases[{index}].expect.limit.max must be a positive integer")
    return LimitExpectation(required=required, maximum=maximum)


def _string_tuple(raw_value: object, index: int, name: str) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list) or not all(
        isinstance(item, str) and item for item in raw_value
    ):
        raise CaseLoadError(f"cases[{index}].expect.{name} must be a list of non-empty strings")
    return tuple(raw_value)


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CaseLoadError(f"{context} must be a mapping with string keys")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CaseLoadError(f"{context} must be a non-empty string")
    return value.strip()
