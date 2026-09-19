# Testing QueryGuard

QueryGuard has three intentionally separate testing layers:

1. Unit tests exercise individual contracts, catalog loading, SQL generation,
   structural validation, policy validation, and facade stage behavior.
2. Deterministic end-to-end acceptance tests exercise the application YAML
   boundary through `QueryGuard.from_yaml`, a test-only generation provider,
   structural validation, policy validation, and `QueryPreparationResult`.
3. Future live-provider evaluations can measure how well a real model produces
   useful SQL for natural-language questions.

Run the normal deterministic suite with:

```bash
python -m pytest
```

Run only the acceptance suite with:

```bash
python -m pytest tests/e2e -q
```

The E2E provider returns predefined strict JSON responses. It makes no live
LLM calls, uses no provider SDK, and connects to no database, so it requires
no API keys and remains repeatable in local and CI runs.

Unit and deterministic E2E tests are correctness and safety tests: they check
that known inputs produce the expected validation decisions and that unsafe
SQL cannot reach approval. They do not measure LLM quality. Live-provider
tests should be kept out of the normal deterministic test suite and run in a
separate evaluation harness with its own credentials, cost controls, and
quality metrics.
