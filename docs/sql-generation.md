# Provider-neutral SQL generation

`SqlGenerationService` is the first, provider-neutral stage of QueryGuard's SQL workflow:

```text
question -> approved catalog -> schema renderer -> prompt -> application provider -> GeneratedSql
```

Applications supply both a `SqlCatalogProvider` and a provider implementing this protocol:

```python
class SqlGenerationProvider(Protocol):
    async def generate(
        self,
        messages: tuple[dict[str, str], ...],
    ) -> str: ...
```

The provider adapter belongs to the consuming application. QueryGuard does not create SDK clients, make network calls, read API keys, or depend on OpenAI, Ollama, Anthropic, Gemini, or any other provider.

## Prompt and schema context

For each request, QueryGuard obtains the approved catalog from the catalog provider and passes it to `render_catalog_for_prompt`. The resulting deterministic schema context includes the catalog dialect, approved tables and selectable columns, relationships, business rules, and global rules.

The message tuple has this exact shape:

1. One `system` message containing generation rules and the rendered schema context.
2. Any caller-supplied `user`, `assistant`, or `system` history messages, copied without mutation.
3. One final `user` message containing the question.

The system message requires read-only SQL, approved schema only, no invented tables or columns, explicit columns instead of `SELECT *`, no SQL execution, and JSON-only output. For a user-scoped query it instructs the provider to use the configured symbolic parameter, such as `@user_id`. No actual account or user value is accepted by the generation API or placed into the prompt.

## Response contract

The provider must return exactly one JSON object compatible with the existing `GeneratedSql` contract:

```json
{
  "sql": "SELECT id FROM orders WHERE account_id = @user_id LIMIT 50",
  "referenced_tables": ["orders"],
  "referenced_columns": ["orders.id", "orders.account_id"],
  "explanation": "Returns the user's orders.",
  "confidence": 0.96
}
```

The response cannot be a list, Markdown code fence, prose-wrapped JSON, multiple JSON objects, an object with unknown fields, or a payload that fails `GeneratedSql` validation. Malformed responses raise `SqlGenerationResponseError`; provider exceptions are wrapped as `SqlGenerationError` with their original exception retained as the cause.

## Stage boundaries

Each `generate()` call makes exactly one provider call. There are no retries, repair calls, reflection loops, automatic structural validation, policy checks, or SQL execution. Applications can observe and compose the stages separately:

```text
generate -> structural validation -> policy validation -> approved SQL

Database execution is outside QueryGuard core; applications that need the SQLAlchemy runtime can compose the separate `queryguard-sqlalchemy` companion package after policy validation.
```
