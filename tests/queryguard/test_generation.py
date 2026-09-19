"""Tests for provider-neutral single-pass SQL generation."""

import asyncio
import json

import pytest

from queryguard import (
    GeneratedSql,
    SqlAnalyticsSettings,
    SqlColumnDefinition,
    SqlGenerationError,
    SqlGenerationResponseError,
    SqlGenerationService,
    SqlSchemaCatalog,
    SqlTableDefinition,
    SqlValidationService,
    StaticSqlCatalogProvider,
)


class StubProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, str], ...]] = []

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        self.calls.append(messages)
        return self.response


class FailingProvider:
    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        raise ProviderFailure("provider unavailable")


class ProviderFailure(Exception):
    pass


VALID_RESPONSE = json.dumps(
    {
        "sql": "SELECT id FROM orders WHERE account_id = @account_id LIMIT 50",
        "referenced_tables": ["orders"],
        "referenced_columns": ["orders.id", "orders.account_id"],
        "explanation": "Returns the account orders.",
        "confidence": 0.96,
    }
)


def _service(provider: object) -> SqlGenerationService:
    catalog = SqlSchemaCatalog(
        catalog_name="commerce",
        catalog_version="1",
        dialect="postgresql",
        tables=(
            SqlTableDefinition(
                name="orders",
                description="Customer orders",
                user_scoped=True,
                columns=(
                    SqlColumnDefinition(
                        name="id",
                        description="Order identifier",
                        data_type="uuid",
                        is_primary_key=True,
                    ),
                    SqlColumnDefinition(
                        name="account_id",
                        description="Owning account identifier",
                        data_type="uuid",
                        is_user_scope=True,
                    ),
                ),
            ),
        ),
    )
    return SqlGenerationService(
        StaticSqlCatalogProvider(catalog),
        provider,  # type: ignore[arg-type]
        SqlAnalyticsSettings(required_scope_parameter="account_id"),
    )


def _generate(
    service: SqlGenerationService, question: str = "List my orders", **kwargs: object
) -> GeneratedSql:
    return asyncio.run(service.generate(question, **kwargs))  # type: ignore[arg-type]


def test_valid_structured_provider_response_returns_existing_generated_sql_contract():
    result = _generate(_service(StubProvider(VALID_RESPONSE)))
    assert type(result) is GeneratedSql


def test_sql_is_preserved():
    result = _generate(_service(StubProvider(VALID_RESPONSE)))
    assert result.sql == "SELECT id FROM orders WHERE account_id = @account_id LIMIT 50"


def test_referenced_tables_are_converted_to_tuple():
    result = _generate(_service(StubProvider(VALID_RESPONSE)))
    assert result.referenced_tables == ("orders",)


def test_referenced_columns_are_converted_to_tuple():
    result = _generate(_service(StubProvider(VALID_RESPONSE)))
    assert result.referenced_columns == ("orders.id", "orders.account_id")


def test_explanation_is_preserved():
    result = _generate(_service(StubProvider(VALID_RESPONSE)))
    assert result.explanation == "Returns the account orders."


def test_confidence_is_preserved():
    result = _generate(_service(StubProvider(VALID_RESPONSE)))
    assert result.confidence == 0.96


def test_provider_is_called_exactly_once():
    provider = StubProvider(VALID_RESPONSE)
    _generate(_service(provider))
    assert len(provider.calls) == 1


def test_provider_receives_rendered_schema_context():
    provider = StubProvider(VALID_RESPONSE)
    _generate(_service(provider))
    assert "Database dialect: postgresql" in provider.calls[0][0]["content"]
    assert "Table: orders" in provider.calls[0][0]["content"]


def test_provider_receives_question():
    provider = StubProvider(VALID_RESPONSE)
    _generate(_service(provider), "How many orders are there?")
    assert provider.calls[0][-1] == {"role": "user", "content": "How many orders are there?"}


def test_prompt_uses_required_symbolic_scope_parameter():
    provider = StubProvider(VALID_RESPONSE)
    _generate(_service(provider))
    assert "@account_id" in provider.calls[0][0]["content"]


def test_prompt_never_requires_an_actual_runtime_identifier():
    provider = StubProvider(VALID_RESPONSE)
    _generate(_service(provider))
    assert "12345" not in "\n".join(message["content"] for message in provider.calls[0])
    assert "actual user or account identifier" in provider.calls[0][0]["content"]


def test_conversation_history_is_included_correctly():
    provider = StubProvider(VALID_RESPONSE)
    history = ({"role": "assistant", "content": "Earlier answer"},)
    _generate(_service(provider), conversation_history=history)
    assert provider.calls[0][1] == history[0]


def test_caller_history_is_not_mutated():
    provider = StubProvider(VALID_RESPONSE)
    history = ({"role": "user", "content": "Earlier question"},)
    _generate(_service(provider), conversation_history=history)
    assert history == ({"role": "user", "content": "Earlier question"},)
    assert provider.calls[0][1] is not history[0]


def test_malformed_json_raises_response_error():
    with pytest.raises(SqlGenerationResponseError, match="exactly one JSON object"):
        _generate(_service(StubProvider("{")))


def test_markdown_fenced_json_is_rejected():
    response = f"```json\n{VALID_RESPONSE}\n```"
    with pytest.raises(SqlGenerationResponseError):
        _generate(_service(StubProvider(response)))


def test_prose_wrapped_json_is_rejected():
    with pytest.raises(SqlGenerationResponseError):
        _generate(_service(StubProvider(f"Here is the SQL: {VALID_RESPONSE}")))


def test_missing_sql_raises_response_error():
    response = json.dumps({"referenced_tables": ["orders"]})
    with pytest.raises(SqlGenerationResponseError, match="GeneratedSql"):
        _generate(_service(StubProvider(response)))


def test_invalid_confidence_raises_response_error():
    response = json.dumps({"sql": "SELECT id FROM orders", "confidence": 1.5})
    with pytest.raises(SqlGenerationResponseError, match="GeneratedSql"):
        _generate(_service(StubProvider(response)))


def test_json_list_instead_of_object_is_rejected():
    with pytest.raises(SqlGenerationResponseError, match="must be an object"):
        _generate(_service(StubProvider("[]")))


def test_provider_exception_is_wrapped_as_generation_error():
    with pytest.raises(SqlGenerationError, match="provider failed") as exc_info:
        _generate(_service(FailingProvider()))
    assert isinstance(exc_info.value.__cause__, ProviderFailure)


def test_empty_question_is_rejected_before_provider_call():
    provider = StubProvider(VALID_RESPONSE)
    with pytest.raises(SqlGenerationError, match="question must not be empty"):
        _generate(_service(provider), "")
    assert provider.calls == []


def test_whitespace_question_is_rejected_before_provider_call():
    provider = StubProvider(VALID_RESPONSE)
    with pytest.raises(SqlGenerationError, match="question must not be empty"):
        _generate(_service(provider), "  \n\t")
    assert provider.calls == []


def test_validation_service_is_not_invoked_automatically(monkeypatch: pytest.MonkeyPatch):
    def fail_if_called(self: object, value: object) -> object:
        raise AssertionError("validation must not run during generation")

    monkeypatch.setattr(SqlValidationService, "validate", fail_if_called)
    assert _generate(_service(StubProvider(VALID_RESPONSE))).sql.startswith("SELECT")
