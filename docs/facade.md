# Unified preparation facade

`QueryGuard` is a convenience layer over the existing public services. It does not replace low-level composition and it does not execute SQL.

```text
question -> generation -> structural validation -> policy validation -> approved SQL
```

## Construction

Use explicit dependencies when the application already owns a catalog provider:

```python
guard = QueryGuard(
    catalog_provider=provider,
    generation_provider=my_provider,
    settings=settings,
)
```

For the common YAML case:

```python
guard = QueryGuard.from_yaml(
    "catalog.yaml",
    provider=my_provider,
)
```

`from_yaml` delegates to the existing YAML loader, wraps the catalog in `StaticSqlCatalogProvider`, and constructs the same facade. It does not duplicate catalog parsing.

## Preparation and short-circuiting

```python
result = await guard.prepare("How many orders were placed this month?")
if result.approved:
    approved_sql = result.generated.sql
```

The stage is always one of `generation`, `structural_validation`, `policy_validation`, or `approved`. Generation makes exactly one provider call. A generation failure stops before structural validation. A structural failure stops before policy validation. A policy failure returns the structured structural and policy results without repair or retry.

`approved=True` means QueryGuard has approved the generated SQL through both validation stages. It does not mean that SQL has executed successfully.

## Direct SQL validation

Callers that already have SQL can bypass generation:

```python
result = guard.validate_sql(sql)
```

This runs structural validation followed by policy validation and never calls the generation provider. `generated` is `None` for this path; the structured `structural` and `policy` results remain available.

## Agent usage

An agent should treat QueryGuard as an approval gate and choose execution separately:

```python
result = await guard.prepare(question)
if result.approved:
    rows = await sql_tool.execute(
        result.generated.sql,
        parameters={"user_id": runtime_user_id},
    )
```

QueryGuard does not call `sql_tool`, an SQLAlchemy Session, or any HTTP/database tool. It has no retries, repair/reflection loop, answer synthesis, or execution dependency. Low-level `SqlGenerationService`, `SqlValidationService`, `SqlPolicyValidationService`, YAML loaders, and catalog providers remain public for advanced callers.
