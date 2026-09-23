"""Metadata comparison for QueryGuard structural validation.

Responsibility:
- Comparing LLM/provider-reported metadata with SQLGlot-derived authoritative metadata
- referenced_tables mismatch warnings
- referenced_columns mismatch warnings
- Deterministic normalization/sorting
- Warning construction

Does NOT own:
- Parsing (see parsing.py)
- Table/column resolution (see tables.py, columns.py)
"""

from __future__ import annotations

from queryguard.validation.parsing import normalize_identifier


def compare_metadata(
    model_tables: set[str],
    model_columns: set[str],
    parsed_tables: set[str],
    parsed_columns: set[str],
) -> list[str]:
    """Compare model-reported references with parsed references.

    Returns warnings when the LLM's self-reported metadata differs from
    what SQLGlot actually found in the AST.
    """
    warnings: list[str] = []

    if model_tables:
        model_norm = {normalize_identifier(t) for t in model_tables}
        parsed_norm = {normalize_identifier(t) for t in parsed_tables}
        if model_norm != parsed_norm:
            warnings.append("Model-reported tables differ from parsed SQL references.")

    if model_columns:
        model_norm = {normalize_identifier(c) for c in model_columns}
        parsed_norm = {normalize_identifier(c) for c in parsed_columns}
        if model_norm != parsed_norm:
            warnings.append("Model-reported columns differ from parsed SQL references.")

    return warnings


def deduplicate_errors(errors: list) -> list:
    """Deduplicate errors by stable key (code, context, line, column)."""
    seen: set[tuple] = set()
    unique: list = []
    for err in errors:
        key = (err.code, err.context, err.line, err.column)
        if key not in seen:
            seen.add(key)
            unique.append(err)
    return unique
