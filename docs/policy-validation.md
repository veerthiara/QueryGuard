# Policy validation

`SqlPolicyValidationService` is the policy stage after structural validation:

```text
generate -> structural validation -> policy validation -> execution adapter (future)
```

Structural validation determines whether SQL has an allowed shape and uses approved schema objects. Policy validation applies user-scope and result-bound rules to that parsed SQL. It does not execute SQL and is not, by itself, a complete database security boundary.

## User scope

For a catalog table with `user_scoped: true` and `scope_strategy: direct`, each physical read must prove equality between an `is_user_scope` column and the configured symbolic parameter. The default is `@user_id`; applications can configure `SqlAnalyticsSettings(required_scope_parameter=...)`.

```sql
SELECT o.id
FROM orders AS o
WHERE o.account_id = @user_id
LIMIT 100
```

Aliases and reversed equality are supported. A wrong column or parameter does not prove scope. Scope columns cannot be compared to literals, and any `OR` in a scope's predicate is conservatively rejected as ambiguous.

The validator walks every SQLGlot scope. CTEs, nested subqueries, and correlated subqueries must scope the physical read in the scope where it occurs; an outer filter cannot repair an unscoped CTE or inner query. Repeated reads of one physical table each require proof, while `scoped_tables` returns only sorted, deduplicated physical names. Multiple user-scoped tables each require their own direct predicate; join relationships do not infer scope.

Supported bind parameter forms are `@name`, `$1`, and `?`. Parameters are extracted from SQLGlot AST nodes, so strings such as `'@user_id'` are not reported. `detected_parameters` is sorted and deduplicated.

## Result bounds

Row-returning top-level queries require a positive integer-literal `LIMIT` no larger than `max_result_limit`. The final limit is returned as `effective_limit`; inner and branch-only limits do not count.

Scalar selects without `FROM` and non-grouped single-row aggregates may omit `LIMIT`. `GROUP BY` and `DISTINCT` can return multiple rows and therefore require it.

Both `UNION` and `UNION ALL` validate each branch's physical reads independently and require a final result limit. Even aggregate unions require that final bound. A branch-local limit does not bound the union result. This policy layer does not add `INTERSECT` or `EXCEPT` support; structural validation remains responsible for accepting or rejecting SQL shapes.

## Errors and limitations

Policy errors are deterministic: parse/dialect errors return first; then scope errors occur before result-bound errors; identical errors are deduplicated while preserving first occurrence. Stable codes include `USER_SCOPE_REQUIRED`, `USER_SCOPE_PARAMETER_REQUIRED`, `USER_SCOPE_LITERAL_NOT_ALLOWED`, `USER_SCOPE_AMBIGUOUS`, `RESULT_LIMIT_REQUIRED`, `RESULT_LIMIT_TOO_HIGH`, and `INVALID_LIMIT`.

The engine deliberately does not perform full boolean theorem proving, infer scope through joins, repair invalid SQL, validate structural schema access automatically, bind parameters, or execute SQL. Use database permissions and a future read-only execution adapter as additional safeguards.
