"""Deterministic prompt construction for provider-neutral SQL generation."""

_ALLOWED_HISTORY_ROLES = frozenset({"user", "assistant", "system"})


def build_sql_generation_messages(
    *,
    question: str,
    schema_context: str,
    required_scope_parameter: str,
    conversation_history: tuple[dict[str, str], ...] = (),
) -> tuple[dict[str, str], ...]:
    """Build deterministic messages for an injected SQL generation provider."""

    scope_name = required_scope_parameter.strip().lstrip("@")
    if not scope_name:
        raise ValueError("required_scope_parameter must not be empty")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be empty")
    if not isinstance(schema_context, str) or not schema_context.strip():
        raise ValueError("schema_context must not be empty")

    symbolic_scope_parameter = f"@{scope_name}"
    system_content = "\n".join(
        (
            "Generate read-only SQL only.",
            "Use only the approved schema context below and use only its approved tables and columns.",
            "Do not invent tables, columns, relationships, or schema.",
            "Use the SQL dialect declared in the schema context.",
            f"For user-scoped queries, use the symbolic scope parameter {symbolic_scope_parameter} exactly.",
            "Never embed an actual user or account identifier in SQL or in your response.",
            "Prefer explicit columns and never use SELECT *.",
            "Do not execute SQL.",
            "Return exactly one JSON object with these keys: sql, referenced_tables, referenced_columns, explanation, confidence.",
            "Do not include Markdown, code fences, prose before or after the JSON object, or multiple JSON objects.",
            "Approved schema context:\n" + schema_context,
        )
    )

    copied_history = tuple(
        _copy_history_message(message, index) for index, message in enumerate(conversation_history)
    )
    return (
        {"role": "system", "content": system_content},
        *copied_history,
        {"role": "user", "content": question.strip()},
    )


def _copy_history_message(message: dict[str, str], index: int) -> dict[str, str]:
    if not isinstance(message, dict):
        raise ValueError(f"conversation_history[{index}] must be a dictionary")
    role = message.get("role")
    content = message.get("content")
    if role not in _ALLOWED_HISTORY_ROLES:
        raise ValueError(f"conversation_history[{index}] has an unsupported role")
    if not isinstance(content, str):
        raise ValueError(f"conversation_history[{index}].content must be a string")
    return {"role": role, "content": content}
