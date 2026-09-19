"""Provider-neutral, single-pass SQL generation."""

import json
from typing import Protocol

from pydantic import ValidationError

from queryguard.catalog import SqlCatalogProvider
from queryguard.contracts import GeneratedSql
from queryguard.prompts import build_sql_generation_messages
from queryguard.renderer import render_catalog_for_prompt
from queryguard.settings import SqlAnalyticsSettings


class SqlGenerationError(RuntimeError):
    """Raised when SQL generation cannot complete."""


class SqlGenerationResponseError(SqlGenerationError):
    """Raised when a provider response is not one valid GeneratedSql JSON object."""


class SqlGenerationProvider(Protocol):
    """Application-supplied provider capable of one asynchronous generation call."""

    async def generate(self, messages: tuple[dict[str, str], ...]) -> str:
        """Return one JSON-formatted generated SQL response."""
        ...


class SqlGenerationService:
    """Generate a SQL candidate without performing validation or execution."""

    def __init__(
        self,
        catalog_provider: SqlCatalogProvider,
        provider: SqlGenerationProvider,
        settings: SqlAnalyticsSettings | None = None,
    ) -> None:
        self._catalog_provider = catalog_provider
        self._provider = provider
        self._settings = settings or SqlAnalyticsSettings()

    async def generate(
        self,
        question: str,
        *,
        conversation_history: tuple[dict[str, str], ...] = (),
    ) -> GeneratedSql:
        """Generate one strict JSON SQL candidate from an injected provider."""

        if not isinstance(question, str) or not question.strip():
            raise SqlGenerationError("question must not be empty")

        catalog = self._catalog_provider.get_catalog()
        schema_context = render_catalog_for_prompt(catalog)
        try:
            messages = build_sql_generation_messages(
                question=question,
                schema_context=schema_context,
                required_scope_parameter=self._settings.required_scope_parameter,
                conversation_history=conversation_history,
            )
        except ValueError as exc:
            raise SqlGenerationError("invalid SQL generation request") from exc

        try:
            response = await self._provider.generate(messages)
        except Exception as exc:
            raise SqlGenerationError("SQL generation provider failed") from exc

        return _parse_provider_response(response)


_GENERATED_SQL_KEYS = frozenset(
    {"sql", "referenced_tables", "referenced_columns", "explanation", "confidence"}
)


def _parse_provider_response(response: str) -> GeneratedSql:
    """Strictly parse a provider's single JSON object into the existing contract."""

    if not isinstance(response, str):
        raise SqlGenerationResponseError("provider response must be a JSON string")
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise SqlGenerationResponseError(
            "provider response must be exactly one JSON object"
        ) from exc

    if not isinstance(payload, dict):
        raise SqlGenerationResponseError("provider response JSON must be an object")
    unknown_keys = set(payload) - _GENERATED_SQL_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise SqlGenerationResponseError(f"provider response contains unknown field(s): {names}")
    try:
        return GeneratedSql.model_validate(payload)
    except ValidationError as exc:
        raise SqlGenerationResponseError("provider response does not match GeneratedSql") from exc
