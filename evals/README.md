# QueryGuard live evaluations

This directory contains opt-in, local-model evaluation tooling. It is not part
of QueryGuard's runtime package and is never run by `pytest`, `make check`, or
deterministic CI.

The runner sends QueryGuard's ordinary generation prompt and user question to a
locally running Ollama model. It then evaluates the candidate through the public
facade path:

```text
QueryGuard.from_yaml(...) -> prepare(question) -> generation -> structural validation -> policy validation
```

Run `ollama list` to discover local models, then run one model explicitly:

```bash
python evals/run_eval.py --model <model-name>
python evals/run_eval.py --model <model-name> --safety-only
python evals/run_eval.py --model <model-name> --category joins --runs-per-case 3
```

The default case file is `cases/commerce.yaml`; reports go to ignored files
under `results/latest.json` and `results/latest.md`. Cases are property based:
they assert tables, columns, aggregation, grouping, ordering, scope, bounds,
and approval expectations instead of one exact SQL string.

The harness uses only Python's standard-library HTTP client for Ollama. No
cloud provider, API key, database, or provider SDK is required.
