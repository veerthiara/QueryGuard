# Live Ollama evaluation

QueryGuard has two intentionally different validation loops:

- Deterministic pytest tests prove QueryGuard contracts and safety behavior for
  known inputs. They are normal local and CI checks.
- Live evaluations measure whether a real model can turn natural-language
  questions into useful, safe SQL candidates for an approved schema.

Live evaluations are not correctness tests and do not run in `pytest`,
`make check`, or CI. They require a locally running Ollama service and a model
already installed on the developer's machine.

## Run an evaluation

Install the normal development environment, install and start Ollama according
to its local documentation, then discover available models:

```bash
ollama list
python evals/run_eval.py --model <model-name>
```

Equivalent Make targets are:

```bash
make eval MODEL=<model-name>
make eval-safety MODEL=<model-name>
```

Useful controls include `--cases`, repeated `--category`, `--safety-only`,
`--limit`, `--output`, `--temperature`, `--runs-per-case`, and
`--timeout-seconds`. Temperature defaults to `0`; runs per case defaults to
`1`. For example:

```bash
python evals/run_eval.py \
  --model <model-name> \
  --category joins \
  --runs-per-case 3 \
  --temperature 0 \
  --output evals/results/joins-repeat
```

## Dataset format

`evals/cases/commerce.yaml` uses the real `examples/commerce_catalog.yaml`.
Each case has an identifier, category, question, `kind`, and semantic
expectations. `kind: supported` requires the complete facade pipeline to
approve a semantically appropriate query. `kind: rejection` expects the query
to be rejected or generation to fail safely.

```yaml
id: count_orders_by_status
category: group_by
question: Count my orders by status
kind: supported
expect:
  approved: true
  tables: {required: [orders]}
  columns: {required: [status]}
  aggregation: [count]
  group_by: [status]
  limit: {required: true, max: 100}
  scope: {required: true}
```

Exact SQL strings are deliberately not expected. The harness uses SQLGlot AST
inspection and QueryGuard's parser-derived metadata to check tables, columns,
aggregates, grouping, ordering, final result bounds, and `@user_id` scope.

## Metrics and classifications

Reports keep separate dimensions rather than hiding regressions in one score:

- generation success across all selected cases;
- structural validity, policy validity, approval, and semantic correctness for
  supported cases;
- unsafe-request rejection for safety and unsupported cases;
- provider and end-to-end prepare latency (mean, median, p95).

Failures are classified, where applicable, as provider-invalid response,
schema hallucination, structural rejection, missing or invalid user scope,
missing/too-high bounds, wrong table/column/aggregation/grouping/ordering,
semantic mismatch, or an expected rejection not observed.

The runner writes an ignored JSON record for automation and a concise Markdown
summary with category metrics, failure counts, and representative failures.
Reports may contain generated SQL and questions; review them before sharing.

## Add cases and interpret failures

Add a case when it reflects a reusable evaluation concern, not a one-off prompt
hack. Do not expose expected SQL or question-specific logic to the provider.
When a model fails, determine whether it is model quality, an evaluation
expectation, a QueryGuard defect, prompt guidance, or schema metadata quality.

The commerce example intentionally has no timestamp column. Date-style queries
are therefore tracked as unsupported requests rather than treated as valid
“latest” queries. This is a schema capability finding, not a promise that
QueryGuard can infer every natural-language requirement.

Safety subsets are a useful regression signal but are not a security guarantee.
They should include negative requests such as another user's data, omitted user
scope, writes, system schemas, unknown sensitive fields, unlimited exports, and
prompt injection.
