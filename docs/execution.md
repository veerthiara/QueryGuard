# Optional read-only execution

Execution is the final QueryGuard stage and receives SQL that has already passed structural and policy validation:

```text
generate -> structural validation -> policy validation -> execute
```

`SqlExecutionService` intentionally does not call either validator. It accepts an injected `SqlExecutor`, validates executable `@name` parameter names, rejects missing or extra parameters, then makes exactly one executor call. It does not retry, repair, execute a probe query, or synthesize answers.

## SQLAlchemy adapter

SQLAlchemy is optional. Core users do not need it. Install the integration with:

```bash
python -m pip install "queryguard[sqlalchemy]"
```

```python
from queryguard import SqlExecutionService
from queryguard.adapters.sqlalchemy import SqlAlchemyExecutor

service = SqlExecutionService(SqlAlchemyExecutor(session))
result = await service.execute(
    "SELECT id FROM orders WHERE account_id = @user_id LIMIT 100",
    {"user_id": runtime_user_id},
)
```

This revision supports an injected **synchronous SQLAlchemy Session-compatible object** called directly by the async service. It does not create engines, read database URLs, create sessions, or support `AsyncSession`.

If `queryguard.adapters.sqlalchemy` is imported without the extra, it raises an `ImportError` explaining how to install `queryguard[sqlalchemy]`.

## Parameter binding

The SQLAlchemy adapter converts executable `@name` placeholders to `:name` binds. The scanner leaves single-quoted strings, double-quoted identifiers, line comments, block comments, and PostgreSQL dollar-quoted strings unchanged. Only named `@name` placeholders are executable-adapter inputs; values are supplied separately and are never interpolated into SQL text.

The generic service rejects both missing parameters and unused extras with `PARAMETER_BINDING_ERROR`. This catches caller/configuration mistakes deterministically.

## Read-only protections and timeout

For a PostgreSQL-bound Session, the adapter runs `SET TRANSACTION READ ONLY` and applies `set_config('statement_timeout', :timeout_ms, true)`. The timeout is transaction-local, uses `SqlAnalyticsSettings.statement_timeout_ms`, and does not globally leak connection state. These are defense-in-depth measures, not a replacement for read-only database credentials, grants, connection routing, or prior validation.

## Results and errors

The adapter fetches at most `max_rows + 1` rows, returns at most `max_rows`, and marks `truncated=True` when an additional row was observed. Rows are normalized to ordered column-keyed dictionaries; `row_count` is the number returned to the caller. Scalar values remain unmodified.

Public errors do not include database details, SQL text, credentials, DSNs, or parameter values. Stable codes are `PARAMETER_BINDING_ERROR`, `EXECUTION_TIMEOUT`, `READ_ONLY_VIOLATION`, and `EXECUTION_FAILED`. The analytics SQL executes exactly once after binding validation; setup statements for PostgreSQL protections are not user-query retries.
