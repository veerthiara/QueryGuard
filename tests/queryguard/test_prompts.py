"""Tests for deterministic SQL generation prompts."""

import pytest

from queryguard import build_sql_generation_messages

SCHEMA_CONTEXT = "Database dialect: postgresql\nTable: orders\nColumns:\n- id (uuid)"


def test_prompt_output_is_deterministic():
    kwargs = {
        "question": "List orders",
        "schema_context": SCHEMA_CONTEXT,
        "required_scope_parameter": "user_id",
    }
    assert build_sql_generation_messages(**kwargs) == build_sql_generation_messages(**kwargs)


def test_prompt_includes_required_safety_and_output_instructions():
    messages = build_sql_generation_messages(
        question="List orders",
        schema_context=SCHEMA_CONTEXT,
        required_scope_parameter="user_id",
    )
    content = messages[0]["content"].lower()
    assert "read-only sql" in content
    assert "approved schema" in content
    assert "do not invent tables, columns" in content
    assert "never embed an actual user or account identifier" in content
    assert "json object" in content
    assert "do not include markdown" in content
    assert "never use select *" in content
    assert "every user-scoped physical table read" in content
    assert "final positive limit no greater than 500" in content


def test_prompt_includes_schema_question_and_symbolic_scope_parameter():
    messages = build_sql_generation_messages(
        question="List orders",
        schema_context=SCHEMA_CONTEXT,
        required_scope_parameter="account_id",
    )
    assert SCHEMA_CONTEXT in messages[0]["content"]
    assert "@account_id" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "List orders"}


def test_prompt_includes_history_without_mutating_caller_history():
    history = ({"role": "user", "content": "Earlier question"},)
    messages = build_sql_generation_messages(
        question="List orders",
        schema_context=SCHEMA_CONTEXT,
        required_scope_parameter="user_id",
        conversation_history=history,
    )
    assert messages[1] == history[0]
    assert messages[1] is not history[0]
    assert history == ({"role": "user", "content": "Earlier question"},)


def test_prompt_rejects_unsupported_history_role():
    with pytest.raises(ValueError, match="unsupported role"):
        build_sql_generation_messages(
            question="List orders",
            schema_context=SCHEMA_CONTEXT,
            required_scope_parameter="user_id",
            conversation_history=({"role": "tool", "content": "not allowed"},),
        )
