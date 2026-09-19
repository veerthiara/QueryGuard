"""Behavioral tests for generic SQL policy validation."""

import pytest

from queryguard import (
    SqlAnalyticsSettings,
    SqlColumnDefinition,
    SqlPolicyError,
    SqlPolicyValidationResult,
    SqlPolicyValidationService,
    SqlSchemaCatalog,
    SqlTableDefinition,
    StaticSqlCatalogProvider,
)


def _commerce_catalog() -> SqlSchemaCatalog:
    return SqlSchemaCatalog(
        catalog_name="commerce",
        catalog_version="1",
        dialect="postgresql",
        tables=(
            SqlTableDefinition(
                name="customers",
                description="Customer accounts",
                columns=(
                    SqlColumnDefinition(name="id", description="Customer ID", data_type="uuid", is_primary_key=True),
                    SqlColumnDefinition(name="account_id", description="Account ID", data_type="uuid"),
                    SqlColumnDefinition(name="name", description="Customer name", data_type="text"),
                ),
            ),
            SqlTableDefinition(
                name="orders",
                description="Customer orders",
                user_scoped=True,
                scope_strategy="direct",
                columns=(
                    SqlColumnDefinition(name="id", description="Order ID", data_type="uuid", is_primary_key=True),
                    SqlColumnDefinition(name="account_id", description="Account ID", data_type="uuid", is_user_scope=True),
                    SqlColumnDefinition(name="customer_id", description="Customer ID", data_type="uuid"),
                    SqlColumnDefinition(name="total_cents", description="Order total", data_type="integer"),
                    SqlColumnDefinition(name="status", description="Order status", data_type="text"),
                ),
            ),
            SqlTableDefinition(
                name="order_items",
                description="Order line items",
                user_scoped=True,
                scope_strategy="direct",
                columns=(
                    SqlColumnDefinition(name="id", description="Item ID", data_type="uuid", is_primary_key=True),
                    SqlColumnDefinition(name="account_id", description="Account ID", data_type="uuid", is_user_scope=True),
                    SqlColumnDefinition(name="order_id", description="Order ID", data_type="uuid"),
                    SqlColumnDefinition(name="product_name", description="Product name", data_type="text"),
                ),
            ),
        ),
    )


@pytest.fixture
def policy() -> SqlPolicyValidationService:
    return SqlPolicyValidationService(
        StaticSqlCatalogProvider(_commerce_catalog()),
        SqlAnalyticsSettings(required_scope_parameter="user_id", default_result_limit=50, max_result_limit=500),
    )


def _codes(result: SqlPolicyValidationResult) -> list[str]:
    return [error.code for error in result.errors]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", ()),
        ("SELECT id FROM orders WHERE account_id = @user_id LIMIT 10", ("user_id",)),
        ("SELECT id FROM customers WHERE account_id = $1 LIMIT 10", ("1",)),
        ("SELECT id FROM customers WHERE account_id = ? LIMIT 10", ("?",)),
        ("SELECT '@user_id', ':user_id'", ()),
    ],
)
def test_parameter_detection_is_ast_based_and_sorted(policy, sql, expected):
    assert policy.validate(sql).detected_parameters == expected


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM orders WHERE account_id = @user_id LIMIT 10",
        "SELECT o.id FROM orders o WHERE o.account_id = @user_id LIMIT 10",
        "SELECT id FROM orders WHERE @user_id = account_id LIMIT 10",
        "SELECT id FROM orders WHERE status = 'done' AND account_id = @user_id LIMIT 10",
    ],
)
def test_direct_scope_predicates_are_accepted(policy, sql):
    result = policy.validate(sql)
    assert result.valid is True
    assert result.scoped_tables == ("orders",)


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT id FROM orders WHERE id = @user_id", "USER_SCOPE_REQUIRED"),
        ("SELECT id FROM orders WHERE account_id = @other_id", "USER_SCOPE_PARAMETER_REQUIRED"),
        ("SELECT id FROM orders WHERE account_id = 'literal'", "USER_SCOPE_LITERAL_NOT_ALLOWED"),
        ("SELECT id FROM orders WHERE account_id = 123", "USER_SCOPE_LITERAL_NOT_ALLOWED"),
        ("SELECT id FROM orders WHERE account_id <> @user_id", "USER_SCOPE_REQUIRED"),
    ],
)
def test_invalid_direct_scope_predicates_are_rejected(policy, sql, code):
    assert code in _codes(policy.validate(sql))


def test_or_scope_predicate_is_rejected_conservatively(policy):
    result = policy.validate("SELECT id FROM orders WHERE account_id = @user_id OR status = 'public'")
    assert "USER_SCOPE_AMBIGUOUS" in _codes(result)


def test_non_user_scoped_table_needs_no_scope(policy):
    result = policy.validate("SELECT id FROM customers LIMIT 10")
    assert result.valid is True
    assert result.scoped_tables == ()


def test_unsupported_scope_strategy_is_rejected():
    catalog = SqlSchemaCatalog(
        catalog_name="test",
        catalog_version="1",
        tables=(
            SqlTableDefinition(
                name="data",
                description="Data",
                user_scoped=True,
                scope_strategy="relationship",
                columns=(SqlColumnDefinition(name="account_id", description="Account", data_type="uuid", is_user_scope=True),),
            ),
        ),
    )
    result = SqlPolicyValidationService(StaticSqlCatalogProvider(catalog)).validate(
        "SELECT account_id FROM data WHERE account_id = @user_id LIMIT 10"
    )
    assert _codes(result) == ["USER_SCOPE_UNSUPPORTED"]


def test_cte_inner_scoped_read_is_valid(policy):
    result = policy.validate(
        "WITH scoped_orders AS (SELECT id FROM orders WHERE account_id = @user_id) "
        "SELECT id FROM scoped_orders LIMIT 10"
    )
    assert result.valid is True
    assert result.scoped_tables == ("orders",)


@pytest.mark.parametrize(
    "sql",
    [
        "WITH orders_cte AS (SELECT id FROM orders) SELECT id FROM orders_cte LIMIT 10",
        "WITH orders_cte AS (SELECT id, account_id FROM orders) "
        "SELECT id FROM orders_cte WHERE account_id = @user_id LIMIT 10",
    ],
)
def test_outer_filters_do_not_repair_unscoped_cte_reads(policy, sql):
    assert "USER_SCOPE_REQUIRED" in _codes(policy.validate(sql))


@pytest.mark.parametrize(
    ("sql", "valid"),
    [
        (
            "SELECT c.name FROM customers c WHERE c.id IN "
            "(SELECT o.customer_id FROM orders o WHERE o.account_id = @user_id) LIMIT 10",
            True,
        ),
        (
            "SELECT c.name FROM customers c WHERE c.id IN "
            "(SELECT o.customer_id FROM orders o) LIMIT 10",
            False,
        ),
        (
            "SELECT c.name FROM customers c WHERE EXISTS (SELECT 1 FROM orders o "
            "WHERE o.customer_id = c.id AND o.account_id = @user_id) LIMIT 10",
            True,
        ),
        (
            "SELECT c.name FROM customers c WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.customer_id = c.id) LIMIT 10",
            False,
        ),
    ],
)
def test_nested_and_correlated_reads_are_validated_in_their_own_scope(policy, sql, valid):
    result = policy.validate(sql)
    assert result.valid is valid
    if valid:
        assert result.scoped_tables == ("orders",)
    else:
        assert "USER_SCOPE_REQUIRED" in _codes(result)


def test_repeated_physical_reads_each_require_scope(policy):
    result = policy.validate(
        "SELECT o.id FROM orders o WHERE o.account_id = @user_id "
        "AND EXISTS (SELECT 1 FROM orders o2 WHERE o2.customer_id = o.customer_id) LIMIT 10"
    )
    assert _codes(result) == ["USER_SCOPE_REQUIRED"]
    assert result.errors[0].context == "orders"


def test_repeated_physical_reads_are_canonically_deduplicated_when_scoped(policy):
    result = policy.validate(
        "SELECT o.id FROM orders o WHERE o.account_id = @user_id "
        "AND EXISTS (SELECT 1 FROM orders o2 WHERE o2.customer_id = o.customer_id "
        "AND o2.account_id = @user_id) LIMIT 10"
    )
    assert result.valid is True
    assert result.scoped_tables == ("orders",)


def test_multiple_user_scoped_tables_must_be_independently_scoped(policy):
    result = policy.validate(
        "SELECT o.id, i.product_name FROM orders o JOIN order_items i ON i.order_id = o.id "
        "WHERE o.account_id = @user_id LIMIT 10"
    )
    assert [(error.code, error.context) for error in result.errors] == [
        ("USER_SCOPE_REQUIRED", "order_items")
    ]


def test_multiple_user_scoped_tables_and_alias_reuse_are_scoped_locally(policy):
    joined = policy.validate(
        "SELECT o.id, i.product_name FROM orders o JOIN order_items i ON i.order_id = o.id "
        "WHERE o.account_id = @user_id AND i.account_id = @user_id LIMIT 10"
    )
    reused_alias = policy.validate(
        "SELECT o.id FROM orders o WHERE o.account_id = @user_id AND EXISTS "
        "(SELECT 1 FROM order_items o WHERE o.order_id = o.id AND o.account_id = @user_id) LIMIT 10"
    )
    assert joined.valid is True
    assert joined.scoped_tables == ("order_items", "orders")
    assert reused_alias.valid is True
    assert reused_alias.scoped_tables == ("order_items", "orders")


def test_row_query_requires_a_top_level_limit(policy):
    result = policy.validate("SELECT id FROM orders WHERE account_id = @user_id")
    assert _codes(result) == ["RESULT_LIMIT_REQUIRED"]
    assert result.effective_limit is None


def test_valid_limit_and_effective_limit(policy):
    result = policy.validate("SELECT id FROM orders WHERE account_id = @user_id LIMIT 25")
    assert result.valid is True
    assert result.effective_limit == 25


def test_max_limit_is_configurable(policy):
    assert policy.validate("SELECT id FROM orders WHERE account_id = @user_id LIMIT 500").valid is True
    assert _codes(policy.validate("SELECT id FROM orders WHERE account_id = @user_id LIMIT 501")) == [
        "RESULT_LIMIT_TOO_HIGH"
    ]


@pytest.mark.parametrize("limit", ["0", "-1", "@limit", "?", "$1", "some_column"])
def test_limit_must_be_a_positive_integer_literal(policy, limit):
    result = policy.validate(f"SELECT id FROM orders WHERE account_id = @user_id LIMIT {limit}")
    assert _codes(result) == ["INVALID_LIMIT"]
    assert result.effective_limit is None


@pytest.mark.parametrize("sql", ["SELECT 1", "SELECT CURRENT_DATE"])
def test_scalar_selects_do_not_require_limit(policy, sql):
    result = policy.validate(sql)
    assert result.valid is True
    assert result.effective_limit is None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM orders WHERE account_id = @user_id",
        "SELECT SUM(total_cents) FROM orders WHERE account_id = @user_id",
        "SELECT COUNT(*), SUM(total_cents) FROM orders WHERE account_id = @user_id",
    ],
)
def test_single_row_aggregates_do_not_require_limit(policy, sql):
    assert policy.validate(sql).valid is True


def test_group_by_and_distinct_require_limit(policy):
    group_by = policy.validate(
        "SELECT status, COUNT(*) FROM orders WHERE account_id = @user_id GROUP BY status"
    )
    distinct = policy.validate("SELECT DISTINCT status FROM orders WHERE account_id = @user_id")
    assert _codes(group_by) == ["RESULT_LIMIT_REQUIRED"]
    assert _codes(distinct) == ["RESULT_LIMIT_REQUIRED"]
    assert policy.validate(
        "SELECT status, COUNT(*) FROM orders WHERE account_id = @user_id GROUP BY status LIMIT 10"
    ).valid is True


def test_cte_inner_limit_does_not_become_the_final_effective_limit(policy):
    result = policy.validate(
        "WITH scoped_orders AS (SELECT id FROM orders WHERE account_id = @user_id LIMIT 5) "
        "SELECT id FROM scoped_orders"
    )
    assert _codes(result) == ["RESULT_LIMIT_REQUIRED"]
    assert result.effective_limit is None


@pytest.mark.parametrize("operator", ["UNION", "UNION ALL"])
def test_set_operations_require_scoped_branches_and_final_limit(policy, operator):
    result = policy.validate(
        "SELECT id FROM orders WHERE account_id = @user_id "
        f"{operator} SELECT id FROM order_items WHERE account_id = @user_id LIMIT 100"
    )
    assert result.valid is True
    assert result.effective_limit == 100
    assert result.scoped_tables == ("order_items", "orders")


def test_union_branch_limit_does_not_bound_final_result(policy):
    result = policy.validate(
        "SELECT id FROM orders WHERE account_id = @user_id LIMIT 5 "
        "UNION ALL SELECT id FROM order_items WHERE account_id = @user_id"
    )
    assert _codes(result) == ["RESULT_LIMIT_REQUIRED"]
    assert result.effective_limit is None


def test_aggregate_union_requires_final_limit(policy):
    result = policy.validate(
        "SELECT COUNT(*) FROM orders WHERE account_id = @user_id "
        "UNION SELECT COUNT(*) FROM order_items WHERE account_id = @user_id"
    )
    assert _codes(result) == ["RESULT_LIMIT_REQUIRED"]


def test_union_errors_are_scope_first_and_duplicates_are_removed(policy):
    result = policy.validate("SELECT id FROM orders UNION SELECT id FROM orders")
    assert [(error.code, error.context) for error in result.errors] == [
        ("USER_SCOPE_REQUIRED", "orders"),
        ("RESULT_LIMIT_REQUIRED", None),
    ]


def test_union_scope_errors_precede_result_errors(policy):
    result = policy.validate("SELECT id FROM orders UNION SELECT id FROM order_items")
    assert [(error.code, error.context) for error in result.errors] == [
        ("USER_SCOPE_REQUIRED", "orders"),
        ("USER_SCOPE_REQUIRED", "order_items"),
        ("RESULT_LIMIT_REQUIRED", None),
    ]


def test_parse_dialect_and_multiple_statement_errors(policy):
    assert _codes(policy.validate("")) == ["EMPTY_SQL"]
    assert _codes(policy.validate("INVALID SQL")) == ["PARSE_ERROR"]
    assert _codes(policy.validate("SELECT 1; SELECT 2")) == ["MULTIPLE_STATEMENTS"]


def test_unsupported_dialect_is_rejected():
    catalog = _commerce_catalog().model_copy(update={"dialect": "mysql"})
    result = SqlPolicyValidationService(StaticSqlCatalogProvider(catalog)).validate("SELECT 1")
    assert _codes(result) == ["UNSUPPORTED_DIALECT"]


def test_policy_contract_consistency_is_preserved():
    error = SqlPolicyError(code="X", message="Failure")
    assert SqlPolicyValidationResult(valid=False, errors=(error,)).errors == (error,)
    with pytest.raises(ValueError):
        SqlPolicyValidationResult(valid=True, errors=(error,))
