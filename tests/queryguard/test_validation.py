"""Tests for SQL Validation Service - Phase 09 Rev 03."""

import pytest

from queryguard.catalog import StaticSqlCatalogProvider
from queryguard.contracts import (
    GeneratedSql,
    SqlColumnDefinition,
    SqlSchemaCatalog,
    SqlTableDefinition,
)
from queryguard.validation import SqlValidationService

# ── Commerce Catalog Fixture ───────────────────────────────────────────────────


def _commerce_catalog() -> SqlSchemaCatalog:
    """Meaningful generic commerce catalog for testing."""
    return SqlSchemaCatalog(
        catalog_name="commerce",
        catalog_version="1",
        dialect="postgresql",
        tables=(
            SqlTableDefinition(
                name="customers",
                description="Customer accounts",
                user_scoped=False,
                allowed_for_select=True,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="Customer ID", data_type="uuid", is_primary_key=True
                    ),
                    SqlColumnDefinition(
                        name="account_id",
                        description="Account ID",
                        data_type="uuid",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="name",
                        description="Customer name",
                        data_type="varchar(255)",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="created_at",
                        description="Account creation",
                        data_type="timestamp with time zone",
                        nullable=False,
                    ),
                ),
            ),
            SqlTableDefinition(
                name="orders",
                description="Customer orders",
                user_scoped=True,
                allowed_for_select=True,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="Order ID", data_type="uuid", is_primary_key=True
                    ),
                    SqlColumnDefinition(
                        name="account_id",
                        description="Account ID",
                        data_type="uuid",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="customer_id",
                        description="Buyer",
                        data_type="uuid",
                        is_foreign_key=True,
                        foreign_key_target="customers.id",
                        is_user_scope=True,
                    ),
                    SqlColumnDefinition(
                        name="total_cents",
                        description="Order total in cents",
                        data_type="integer",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="status",
                        description="Order status",
                        data_type="varchar(50)",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="placed_at",
                        description="Order timestamp",
                        data_type="timestamp with time zone",
                        nullable=False,
                    ),
                ),
            ),
            SqlTableDefinition(
                name="order_items",
                description="Order line items",
                user_scoped=True,
                allowed_for_select=True,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="Item ID", data_type="uuid", is_primary_key=True
                    ),
                    SqlColumnDefinition(
                        name="account_id",
                        description="Account ID",
                        data_type="uuid",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="order_id",
                        description="Order reference",
                        data_type="uuid",
                        is_foreign_key=True,
                        foreign_key_target="orders.id",
                        is_user_scope=True,
                    ),
                    SqlColumnDefinition(
                        name="product_name",
                        description="Product name",
                        data_type="varchar(255)",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="quantity", description="Quantity", data_type="integer", nullable=False
                    ),
                    SqlColumnDefinition(
                        name="unit_price_cents",
                        description="Unit price in cents",
                        data_type="integer",
                        nullable=False,
                    ),
                ),
            ),
            # Hidden table - not allowed for select
            SqlTableDefinition(
                name="internal_audit_log",
                description="Internal audit logging",
                user_scoped=False,
                allowed_for_select=False,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="Log ID", data_type="uuid", is_primary_key=True
                    ),
                    SqlColumnDefinition(
                        name="action",
                        description="Action performed",
                        data_type="varchar(100)",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="performed_at",
                        description="Timestamp",
                        data_type="timestamp with time zone",
                        nullable=False,
                    ),
                ),
            ),
        ),
        relationships=(),
        global_rules=(
            "Only SELECT statements allowed",
            "Always filter by account_id on user-scoped tables",
            "Use LIMIT (default 50, max 100)",
        ),
    )


# ── Test Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def catalog_provider():
    return StaticSqlCatalogProvider(_commerce_catalog())


@pytest.fixture
def validation_service():
    return SqlValidationService(catalog_provider=StaticSqlCatalogProvider(_commerce_catalog()))


# ── TestSqlValidationService ──────────────────────────────────────────────────


class TestSqlValidationService:
    def test_validate_accepts_generated_sql(self, validation_service):
        """Service accepts GeneratedSql object."""
        result = validation_service.validate(GeneratedSql(sql="SELECT 1"))
        assert result.valid is True
        assert result.normalized_sql == "SELECT 1"

    def test_validate_accepts_plain_string(self, validation_service):
        """Service accepts plain string SQL."""
        result = validation_service.validate("SELECT 1")
        assert result.valid is True
        assert result.normalized_sql == "SELECT 1"

    def test_validate_rejects_empty_sql(self, validation_service):
        """Empty SQL is rejected."""
        result = validation_service.validate("")
        assert result.valid is False
        assert any(e.code == "EMPTY_SQL" for e in result.errors)

    def test_validate_rejects_whitespace_only(self, validation_service):
        """Whitespace-only SQL is rejected."""
        result = validation_service.validate("   \n  ")
        assert result.valid is False
        assert any(e.code == "EMPTY_SQL" for e in result.errors)


# ── TestStatementCount ────────────────────────────────────────────────────────


class TestStatementCount:
    def test_multiple_statements_rejected(self, validation_service):
        """Multiple statements are rejected."""
        result = validation_service.validate("SELECT 1; SELECT 2")
        assert result.valid is False
        assert any(e.code == "MULTIPLE_STATEMENTS" for e in result.errors)

    def test_single_statement_allowed(self, validation_service):
        """Single statement is allowed."""
        result = validation_service.validate("SELECT 1")
        assert result.valid is True

    def test_trailing_semicolon_normalized(self, validation_service):
        """Trailing semicolon is normalized."""
        result = validation_service.validate("SELECT 1;")
        assert result.valid is True
        assert result.normalized_sql is not None


# ── TestStatementTypeValidation ────────────────────────────────────────────────


class TestStatementTypeValidation:
    def test_select_allowed(self, validation_service):
        """SELECT is allowed."""
        result = validation_service.validate("SELECT 1")
        assert result.valid is True

    def test_with_select_allowed(self, validation_service):
        """WITH ... SELECT is allowed."""
        result = validation_service.validate(
            "WITH cte AS (SELECT id FROM customers) SELECT id FROM cte"
        )
        assert result.valid is True

    def test_union_allowed(self, validation_service):
        """UNION is allowed."""
        result = validation_service.validate("SELECT id FROM customers UNION SELECT id FROM orders")
        assert result.valid is True

    def test_union_all_allowed(self, validation_service):
        """UNION ALL is allowed."""
        result = validation_service.validate(
            "SELECT id FROM customers UNION ALL SELECT id FROM orders"
        )
        assert result.valid is True

    def test_with_union_allowed(self, validation_service):
        """WITH ... UNION is allowed."""
        result = validation_service.validate(
            "WITH cte AS (SELECT id FROM customers) SELECT id FROM cte UNION SELECT id FROM orders"
        )
        assert result.valid is True

    def test_insert_rejected(self, validation_service):
        """INSERT is rejected."""
        result = validation_service.validate(
            "INSERT INTO orders (id, account_id, customer_id, total_cents, status, placed_at) VALUES ('a','b','c',100,'new',now())"
        )
        assert result.valid is False
        assert any(e.code == "WRITE_OPERATION" for e in result.errors)

    def test_update_rejected(self, validation_service):
        """UPDATE is rejected."""
        result = validation_service.validate("UPDATE orders SET total_cents = 100")
        assert result.valid is False
        assert any(e.code == "WRITE_OPERATION" for e in result.errors)

    def test_delete_rejected(self, validation_service):
        """DELETE is rejected."""
        result = validation_service.validate("DELETE FROM orders")
        assert result.valid is False
        assert any(e.code == "WRITE_OPERATION" for e in result.errors)

    def test_create_rejected(self, validation_service):
        """CREATE is rejected."""
        result = validation_service.validate("CREATE TABLE foo (id INT)")
        assert result.valid is False
        assert any(e.code == "DDL_OPERATION" for e in result.errors)

    def test_drop_rejected(self, validation_service):
        """DROP is rejected."""
        result = validation_service.validate("DROP TABLE orders")
        assert result.valid is False
        assert any(e.code == "DDL_OPERATION" for e in result.errors)

    def test_alter_parsed_as_command_rejected(self, validation_service):
        """ALTER TABLE is parsed as Command and rejected."""
        result = validation_service.validate("ALTER TABLE orders ADD COLUMN foo INT")
        assert result.valid is False
        assert any(e.code in ("DDL_OPERATION", "ADMIN_OPERATION") for e in result.errors)

    def test_truncate_parsed_as_command_rejected(self, validation_service):
        """TRUNCATE TABLE is parsed as Command and rejected."""
        result = validation_service.validate("TRUNCATE TABLE orders")
        assert result.valid is False
        assert any(e.code in ("DDL_OPERATION", "ADMIN_OPERATION") for e in result.errors)


# ── TestWriteOperationsAnywhere ────────────────────────────────────────────────


class TestWriteOperationsAnywhere:
    """Write operations anywhere in AST are rejected or cause parse error."""

    def test_delete_in_subquery_causes_parse_error(self, validation_service):
        """DELETE in subquery causes parse error (parser limitation)."""
        result = validation_service.validate(
            "SELECT * FROM orders WHERE id IN (DELETE FROM orders RETURNING id)"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_insert_in_subquery_causes_parse_error(self, validation_service):
        """INSERT in subquery causes parse error (parser limitation)."""
        result = validation_service.validate(
            "SELECT * FROM (INSERT INTO orders VALUES (1) RETURNING id) t"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_update_in_subquery_causes_parse_error(self, validation_service):
        """UPDATE in subquery causes parse error (parser limitation)."""
        result = validation_service.validate(
            "SELECT * FROM (UPDATE orders SET total_cents = 0 RETURNING id) t"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_write_operation_standalone_rejected(self, validation_service):
        """Standalone write operations are rejected."""
        for sql in [
            "INSERT INTO orders (id, account_id, customer_id, total_cents, status, placed_at) VALUES ('a','b','c',100,'new',now())",
            "UPDATE orders SET total_cents = 0",
            "DELETE FROM orders",
        ]:
            result = validation_service.validate(sql)
            assert result.valid is False
            assert any(
                e.code in ("STATEMENT_NOT_ALLOWED", "WRITE_OPERATION") for e in result.errors
            )


# ── TestWriteOperationsInCTE ──────────────────────────────────────────────────


class TestWriteOperationsInCTE:
    """Write operations inside CTEs cause parse errors (parser limitation)."""

    def test_delete_in_cte_causes_parse_error(self, validation_service):
        """DELETE inside CTE causes parse error (parser limitation)."""
        result = validation_service.validate(
            "WITH deleted AS (DELETE FROM orders RETURNING id) SELECT id FROM deleted"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_update_in_cte_causes_parse_error(self, validation_service):
        """UPDATE inside CTE causes parse error (parser limitation)."""
        result = validation_service.validate(
            "WITH changed AS (UPDATE orders SET total_cents = 0 RETURNING id) SELECT id FROM changed"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_insert_in_cte_causes_parse_error(self, validation_service):
        """INSERT in CTE causes parse error (parser limitation)."""
        result = validation_service.validate(
            "WITH cte AS (INSERT INTO orders (id, account_id, customer_id, total_cents, status, placed_at) VALUES ('a','b','c',100,'new',now()) RETURNING id) SELECT * FROM cte"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_ddl_in_cte_causes_parse_error(self, validation_service):
        """DDL in CTE causes parse error (parser limitation)."""
        result = validation_service.validate(
            "WITH cte AS (CREATE TABLE foo (id INT)) SELECT * FROM cte"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)


# ── TestSystemSchemaAccess ────────────────────────────────────────────────────


class TestSystemSchemaAccess:
    """System schema access is rejected."""

    def test_pg_catalog_rejected(self, validation_service):
        """pg_catalog access rejected."""
        result = validation_service.validate("SELECT * FROM pg_catalog.pg_tables")
        assert result.valid is False
        assert any(e.code == "SYSTEM_SCHEMA_ACCESS" for e in result.errors)

    def test_information_schema_rejected(self, validation_service):
        """information_schema access rejected."""
        result = validation_service.validate("SELECT * FROM information_schema.tables")
        assert result.valid is False
        assert any(e.code == "SYSTEM_SCHEMA_ACCESS" for e in result.errors)

    def test_pg_toast_rejected(self, validation_service):
        """pg_toast access rejected."""
        result = validation_service.validate("SELECT * FROM pg_toast.pg_toast")
        assert result.valid is False
        assert any(e.code == "SYSTEM_SCHEMA_ACCESS" for e in result.errors)

    def test_harmless_alias_allowed(self, validation_service):
        """Harmless alias containing pg_catalog is allowed."""
        result = validation_service.validate("SELECT 'pg_catalog' AS alias FROM customers")
        assert result.valid is True
        # The alias should not be treated as a schema reference


# ── TestDangerousFunctions ────────────────────────────────────────────────────


class TestDangerousFunctions:
    """Dangerous functions are rejected."""

    def test_pg_sleep_rejected(self, validation_service):
        """pg_sleep rejected."""
        result = validation_service.validate("SELECT pg_sleep(10)")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_pg_terminate_backend_rejected(self, validation_service):
        """pg_terminate_backend rejected."""
        result = validation_service.validate("SELECT pg_terminate_backend(123)")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_pg_cancel_backend_rejected(self, validation_service):
        """pg_cancel_backend rejected."""
        result = validation_service.validate("SELECT pg_cancel_backend(123)")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_pg_read_file_rejected(self, validation_service):
        """pg_read_file rejected."""
        result = validation_service.validate("SELECT pg_read_file('/etc/passwd')")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_pg_read_binary_file_rejected(self, validation_service):
        """pg_read_binary_file rejected."""
        result = validation_service.validate("SELECT pg_read_binary_file('/etc/passwd')")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_dblink_connect_rejected(self, validation_service):
        """dblink_connect rejected."""
        result = validation_service.validate("SELECT dblink_connect('conn', 'dbname=postgres')")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_lo_import_rejected(self, validation_service):
        """lo_import rejected."""
        result = validation_service.validate("SELECT lo_import('/etc/passwd')")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_lo_export_rejected(self, validation_service):
        """lo_export rejected."""
        result = validation_service.validate("SELECT lo_export(123, '/tmp/out')")
        assert result.valid is False
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_safe_functions_allowed(self, validation_service):
        """Safe functions like COUNT, SUM allowed."""
        result = validation_service.validate("SELECT COUNT(*), SUM(total_cents) FROM orders")
        assert result.valid is True


# ── TestWildcards ──────────────────────────────────────────────────────────────


class TestWildcards:
    """Wildcard selection is rejected (except COUNT(*))."""

    def test_select_star_rejected(self, validation_service):
        """SELECT * rejected."""
        result = validation_service.validate("SELECT * FROM orders")
        assert result.valid is False
        assert any(e.code == "WILDCARD_NOT_ALLOWED" for e in result.errors)

    def test_select_table_star_rejected(self, validation_service):
        """SELECT table.* rejected."""
        result = validation_service.validate("SELECT orders.* FROM orders")
        assert result.valid is False
        assert any(e.code == "WILDCARD_NOT_ALLOWED" for e in result.errors)

    def test_select_alias_star_rejected(self, validation_service):
        """SELECT alias.* rejected."""
        result = validation_service.validate("SELECT o.* FROM orders o")
        assert result.valid is False
        assert any(e.code == "WILDCARD_NOT_ALLOWED" for e in result.errors)

    def test_count_star_allowed(self, validation_service):
        """COUNT(*) is allowed."""
        result = validation_service.validate("SELECT COUNT(*) FROM orders")
        assert result.valid is True

    def test_count_star_with_other_columns_allowed(self, validation_service):
        """COUNT(*) with other explicit columns is allowed."""
        result = validation_service.validate("SELECT id, COUNT(*) FROM orders GROUP BY id")
        assert result.valid is True


# ── TestTableValidation ────────────────────────────────────────────────────────


class TestTableValidation:
    """Table validation against approved catalog."""

    def test_unknown_table_rejected(self, validation_service):
        """Unknown table rejected."""
        result = validation_service.validate("SELECT id FROM unknown_table")
        assert result.valid is False
        assert any(e.code == "TABLE_NOT_ALLOWED" for e in result.errors)

    def test_hidden_table_rejected(self, validation_service):
        """Non-selectable table rejected."""
        result = validation_service.validate("SELECT id FROM internal_audit_log")
        assert result.valid is False
        assert any(e.code == "TABLE_NOT_ALLOWED" for e in result.errors)

    def test_cte_alias_not_physical_table(self, validation_service):
        """CTE alias is not treated as physical table."""
        result = validation_service.validate(
            "WITH cte AS (SELECT id FROM orders) SELECT id FROM cte"
        )
        assert result.valid is True

    def test_derived_table_alias_not_physical_table(self, validation_service):
        """Derived table alias is not treated as physical table."""
        result = validation_service.validate("SELECT sub.id FROM (SELECT id FROM orders) sub")
        assert result.valid is True

    def test_referenced_tables_sorted_and_canonical(self, validation_service):
        """Referenced tables returned in deterministic sorted order."""
        result = validation_service.validate(
            "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is True
        tables = list(result.referenced_tables)
        assert tables == sorted(tables)
        assert "customers" in tables
        assert "orders" in tables


# ── TestColumnValidation ──────────────────────────────────────────────────────


class TestColumnValidation:
    """Column validation against approved catalog."""

    def test_approved_qualified_column_allowed(self, validation_service):
        """Approved qualified column allowed."""
        result = validation_service.validate("SELECT orders.id, orders.total_cents FROM orders")
        assert result.valid is True

    def test_unknown_qualified_column_rejected(self, validation_service):
        """Unknown qualified column rejected."""
        result = validation_service.validate("SELECT orders.unknown_column FROM orders")
        assert result.valid is False
        assert any(e.code == "COLUMN_NOT_ALLOWED" for e in result.errors)

    def test_approved_unqualified_column_allowed(self, validation_service):
        """Approved unqualified column with single table allowed."""
        result = validation_service.validate("SELECT id FROM orders")
        assert result.valid is True

    def test_ambiguous_unqualified_column_rejected(self, validation_service):
        """Ambiguous unqualified column across joined tables raises error."""
        result = validation_service.validate(
            "SELECT id FROM orders JOIN customers ON orders.customer_id = customers.id"
        )
        assert result.valid is False
        assert any(e.code == "UNQUALIFIED_COLUMN_AMBIGUOUS" for e in result.errors)

    def test_table_alias_column_resolution(self, validation_service):
        """Table alias column resolution works."""
        result = validation_service.validate("SELECT o.id FROM orders o")
        assert result.valid is True

    def test_unknown_table_alias_rejected(self, validation_service):
        """Unknown table alias rejected."""
        result = validation_service.validate("SELECT x.id FROM unknown_alias x")
        assert result.valid is False
        assert any(e.code == "COLUMN_NOT_ALLOWED" for e in result.errors)

    def test_qualified_column_from_cte(self, validation_service):
        """Qualified column from CTE output allowed."""
        result = validation_service.validate(
            "WITH cte AS (SELECT id, account_id FROM customers) SELECT cte.id FROM cte"
        )
        assert result.valid is True

    def test_unqualified_column_from_cte(self, validation_service):
        """Unqualified column from CTE output allowed."""
        result = validation_service.validate(
            "WITH cte AS (SELECT id, account_id FROM customers) SELECT id FROM cte"
        )
        assert result.valid is True

    def test_cte_referenced_columns_use_physical_lineage(self, validation_service):
        """CTE output references report physical catalog columns only."""
        result = validation_service.validate(
            "WITH recent AS (SELECT id, total_cents FROM orders) SELECT recent.id FROM recent"
        )
        assert result.valid is True
        assert result.referenced_tables == ("orders",)
        assert "orders.id" in result.referenced_columns
        assert "orders.total_cents" in result.referenced_columns
        assert all(not col.startswith("cte:") for col in result.referenced_columns)

    def test_derived_referenced_columns_use_physical_lineage(self, validation_service):
        """Derived-table output references report physical catalog columns only."""
        result = validation_service.validate(
            "SELECT sub.order_id FROM (SELECT id AS order_id FROM orders) sub"
        )
        assert result.valid is True
        assert "orders.id" in result.referenced_columns
        assert all(not col.startswith("derived:") for col in result.referenced_columns)

    def test_referenced_columns_sorted_and_canonical(self, validation_service):
        """Referenced columns returned in deterministic sorted order."""
        result = validation_service.validate(
            "SELECT orders.id, orders.total_cents, customers.name FROM orders JOIN customers ON orders.customer_id = customers.id"
        )
        assert result.valid is True
        cols = list(result.referenced_columns)
        assert cols == sorted(cols)
        assert any(c.startswith("customers.") for c in cols)
        assert any(c.startswith("orders.") for c in cols)


# ── TestNestedQueryScope ──────────────────────────────────────────────────────


class TestNestedQueryScope:
    """Nested query scope handling."""

    def test_derived_table_scope_isolation(self, validation_service):
        """Inner query scope doesn't leak to outer."""
        result = validation_service.validate(
            "SELECT sub.x FROM (SELECT id AS x FROM orders) sub WHERE sub.x IS NOT NULL"
        )
        assert result.valid is True

    def test_cte_scope_isolation(self, validation_service):
        """CTE scope doesn't leak to outer query."""
        result = validation_service.validate(
            "WITH cte AS (SELECT id AS x FROM orders) SELECT cte.x FROM cte"
        )
        assert result.valid is True

    def test_scalar_subquery_scope(self, validation_service):
        """Scalar subquery scope handled correctly."""
        result = validation_service.validate(
            "SELECT (SELECT MAX(total_cents) FROM orders) AS max_total"
        )
        assert result.valid is True

    def test_correlated_subquery_scope(self, validation_service):
        """Correlated subquery scope handled correctly."""
        result = validation_service.validate(
            "SELECT c.name FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)"
        )
        assert result.valid is True

    def test_alias_in_inner_scope_not_leak_to_outer(self, validation_service):
        """Alias in inner scope doesn't leak to outer."""
        # Inner query aliases id as inner_alias, outer must use the alias
        result = validation_service.validate(
            "SELECT sub.inner_alias FROM (SELECT id AS inner_alias FROM orders) sub"
        )
        assert result.valid is True

    def test_outer_cannot_reference_inner_alias(self, validation_service):
        """Outer query cannot reference inner scope's projected alias incorrectly."""
        # This should fail - outer tries to use inner alias that doesn't exist in outer scope
        result = validation_service.validate(
            "SELECT inner_alias FROM (SELECT id AS inner_alias FROM orders) sub"
        )
        assert result.valid is False
        assert any(e.code == "COLUMN_NOT_ALLOWED" for e in result.errors)

    def test_nested_cte_name_does_not_leak_outside_scope(self, validation_service):
        """Nested CTE aliases do not hide unrelated physical tables."""
        result = validation_service.validate(
            "SELECT orders.id FROM orders WHERE EXISTS (WITH orders AS (SELECT id FROM customers) SELECT 1 FROM orders)"
        )
        assert result.valid is True
        assert result.referenced_tables == ("customers", "orders")


# ── TestSetOperations ─────────────────────────────────────────────────────────


class TestSetOperations:
    """UNION and UNION ALL validation."""

    def test_union_both_branches_valid(self, validation_service):
        """UNION with both branches valid is allowed."""
        result = validation_service.validate("SELECT id FROM customers UNION SELECT id FROM orders")
        assert result.valid is True

    def test_union_all_both_branches_valid(self, validation_service):
        """UNION ALL with both branches valid is allowed."""
        result = validation_service.validate(
            "SELECT id FROM customers UNION ALL SELECT id FROM orders"
        )
        assert result.valid is True

    def test_union_with_write_in_branch_causes_parse_error(self, validation_service):
        """UNION with write in branch causes parse error (parser limitation)."""
        result = validation_service.validate(
            "SELECT id FROM customers UNION SELECT id FROM (DELETE FROM orders RETURNING id) t"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)


# ── TestMetadataComparison ────────────────────────────────────────────────────


class TestMetadataComparison:
    """Model-reported metadata vs parsed references."""

    def test_matching_metadata_no_warning(self, validation_service):
        """Matching metadata produces no warning."""
        gen_sql = GeneratedSql(
            sql="SELECT orders.id FROM orders",
            referenced_tables=("orders",),
            referenced_columns=("orders.id",),
        )
        result = validation_service.validate(gen_sql)
        assert result.valid is True
        assert len(result.warnings) == 0

    def test_model_tables_differ_warning(self, validation_service):
        """Model tables differ from parsed -> warning."""
        gen_sql = GeneratedSql(
            sql="SELECT orders.id FROM orders",
            referenced_tables=("customers",),  # Wrong!
            referenced_columns=("orders.id",),
        )
        result = validation_service.validate(gen_sql)
        assert result.valid is True
        assert any(
            "Model-reported tables differ from parsed SQL references." in w for w in result.warnings
        )

    def test_model_columns_differ_warning(self, validation_service):
        """Model columns differ from parsed -> warning."""
        gen_sql = GeneratedSql(
            sql="SELECT orders.id FROM orders",
            referenced_tables=("orders",),
            referenced_columns=("orders.total_cents",),  # Wrong!
        )
        result = validation_service.validate(gen_sql)
        assert result.valid is True
        assert any(
            "Model-reported columns differ from parsed SQL references." in w
            for w in result.warnings
        )

    def test_parser_always_wins_for_references(self, validation_service):
        """Parser-derived references always returned in result."""
        gen_sql = GeneratedSql(
            sql="SELECT orders.id FROM orders",
            referenced_tables=("customers",),
            referenced_columns=("customers.name",),
        )
        result = validation_service.validate(gen_sql)
        assert result.referenced_tables == ("orders",)
        assert result.referenced_columns == ("orders.id",)

    def test_plain_string_no_metadata_warnings(self, validation_service):
        """Plain SQL string input produces no metadata warnings."""
        result = validation_service.validate("SELECT orders.id FROM orders")
        assert len(result.warnings) == 0


# ── TestNormalization ─────────────────────────────────────────────────────────


class TestNormalization:
    """Normalized SQL output."""

    def test_normalized_sql_present_when_valid(self, validation_service):
        """Valid query has normalized SQL."""
        result = validation_service.validate("SELECT id FROM orders")
        assert result.normalized_sql is not None
        assert "SELECT" in result.normalized_sql.upper()

    def test_normalized_sql_deterministic(self, validation_service):
        """Normalized SQL is deterministic."""
        result1 = validation_service.validate("SELECT id FROM orders")
        result2 = validation_service.validate("SELECT id FROM orders")
        assert result1.normalized_sql == result2.normalized_sql

    def test_parse_failure_no_normalized_sql(self, validation_service):
        """Parse failure has no normalized SQL."""
        result = validation_service.validate("INVALID SQL")
        assert result.valid is False
        assert result.normalized_sql is None

    def test_validated_but_invalid_query_no_normalized_sql(self, validation_service):
        """Parsed but invalid query (e.g., unknown table) has no normalized SQL."""
        result = validation_service.validate("SELECT * FROM unknown_table")
        assert result.valid is False
        assert result.normalized_sql is None


# ── TestDeterministicOrdering ────────────────────────────────────────────────


class TestDeterministicOrdering:
    """Referenced tables/columns returned in deterministic order."""

    def test_referenced_tables_sorted(self, validation_service):
        """Referenced tables returned in sorted order."""
        result = validation_service.validate(
            "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is True
        tables = list(result.referenced_tables)
        assert tables == sorted(tables)

    def test_referenced_columns_sorted(self, validation_service):
        """Referenced columns returned in sorted order."""
        result = validation_service.validate(
            "SELECT o.id, o.total_cents, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is True
        cols = list(result.referenced_columns)
        assert cols == sorted(cols)


# ── TestErrorDeduplication ────────────────────────────────────────────────────


class TestErrorDeduplication:
    """Prevent duplicate validation errors."""

    def test_dangerous_function_not_duplicated_by_system_schema(self, validation_service):
        """A dangerous function reported once, not by both checks."""
        result = validation_service.validate("SELECT pg_sleep(10)")
        assert result.valid is False
        dangerous_errors = [e for e in result.errors if e.code == "DANGEROUS_FUNCTION"]
        assert len(dangerous_errors) == 1

    def test_write_in_cte_single_error(self, validation_service):
        """Write inside CTE produces one parse error, not duplicates."""
        result = validation_service.validate(
            "WITH cte AS (DELETE FROM orders RETURNING id) SELECT * FROM cte"
        )
        assert result.valid is False
        parse_errors = [e for e in result.errors if e.code == "PARSE_ERROR"]
        assert len(parse_errors) == 1

    def test_multiple_errors_for_different_issues(self, validation_service):
        """Different issues produce separate errors."""
        result = validation_service.validate("SELECT pg_sleep(10), pg_read_file('/etc/passwd')")
        assert result.valid is False
        dangerous_errors = [e for e in result.errors if e.code == "DANGEROUS_FUNCTION"]
        # Both functions should be reported
        assert len(dangerous_errors) == 2


# ── TestStatementTypeErrors ──────────────────────────────────────────────────


class TestStatementTypeErrors:
    """Stable error codes for statement categories."""

    def test_empty_sql_code(self, validation_service):
        """EMPTY_SQL code for empty input."""
        result = validation_service.validate("")
        assert any(e.code == "EMPTY_SQL" for e in result.errors)

    def test_parse_error_code(self, validation_service):
        """PARSE_ERROR code for unparseable SQL."""
        result = validation_service.validate("SELECT 1 FROM")
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_multiple_statements_code(self, validation_service):
        """MULTIPLE_STATEMENTS code for multiple statements."""
        result = validation_service.validate("SELECT 1; SELECT 2")
        assert any(e.code == "MULTIPLE_STATEMENTS" for e in result.errors)

    def test_statement_not_allowed_code(self, validation_service):
        """STATEMENT_NOT_ALLOWED code for disallowed statement types."""
        # INSERT returns WRITE_OPERATION, CALL causes parse error, EXPLAIN returns STATEMENT_NOT_ALLOWED
        result = validation_service.validate("EXPLAIN SELECT 1")
        assert any(e.code == "STATEMENT_NOT_ALLOWED" for e in result.errors)

    def test_write_operation_code(self, validation_service):
        """WRITE_OPERATION code for write operations."""
        result = validation_service.validate("UPDATE orders SET total_cents = 0")
        assert any(e.code in ("WRITE_OPERATION", "STATEMENT_NOT_ALLOWED") for e in result.errors)

    def test_ddl_operation_code(self, validation_service):
        """DDL_OPERATION code for DDL operations."""
        result = validation_service.validate("CREATE TABLE foo (id INT)")
        assert any(e.code in ("DDL_OPERATION", "STATEMENT_NOT_ALLOWED") for e in result.errors)

    def test_admin_operation_code(self, validation_service):
        """ADMIN_OPERATION code for admin operations."""
        result = validation_service.validate("VACUUM orders")
        assert any(e.code in ("ADMIN_OPERATION", "DDL_OPERATION") for e in result.errors)

    def test_system_schema_access_code(self, validation_service):
        """SYSTEM_SCHEMA_ACCESS code for system schema access."""
        result = validation_service.validate("SELECT * FROM pg_catalog.pg_tables")
        assert any(e.code == "SYSTEM_SCHEMA_ACCESS" for e in result.errors)

    def test_dangerous_function_code(self, validation_service):
        """DANGEROUS_FUNCTION code for prohibited functions."""
        result = validation_service.validate("SELECT pg_sleep(10)")
        assert any(e.code == "DANGEROUS_FUNCTION" for e in result.errors)

    def test_table_not_allowed_code(self, validation_service):
        """TABLE_NOT_ALLOWED code for unknown/hidden tables."""
        result = validation_service.validate("SELECT id FROM unknown_table")
        assert any(e.code == "TABLE_NOT_ALLOWED" for e in result.errors)

    def test_column_not_allowed_code(self, validation_service):
        """COLUMN_NOT_ALLOWED code for unknown columns."""
        result = validation_service.validate("SELECT orders.unknown FROM orders")
        assert any(e.code == "COLUMN_NOT_ALLOWED" for e in result.errors)

    def test_unqualified_column_ambiguous_code(self, validation_service):
        """UNQUALIFIED_COLUMN_AMBIGUOUS code for ambiguous columns."""
        result = validation_service.validate(
            "SELECT id FROM orders JOIN customers ON orders.customer_id = customers.id"
        )
        assert any(e.code == "UNQUALIFIED_COLUMN_AMBIGUOUS" for e in result.errors)

    def test_wildcard_not_allowed_code(self, validation_service):
        """WILDCARD_NOT_ALLOWED code for wildcards."""
        result = validation_service.validate("SELECT * FROM orders")
        assert any(e.code == "WILDCARD_NOT_ALLOWED" for e in result.errors)

    def test_unsupported_sql_feature_code(self, validation_service):
        """UNSUPPORTED_SQL_FEATURE code for unsupported features."""
        result = validation_service.validate("SELECT * FROM orders FOR UPDATE")
        assert any(e.code in ("UNSUPPORTED_SQL_FEATURE", "PARSE_ERROR") for e in result.errors)

    def test_unsupported_dialect_code(self, validation_service):
        """UNSUPPORTED_DIALECT code for unsupported catalog dialect."""
        # Create a catalog with unsupported dialect
        from queryguard.contracts import SqlColumnDefinition, SqlSchemaCatalog, SqlTableDefinition

        bad_catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1",
            dialect="mysql",  # Unsupported
            tables=(
                SqlTableDefinition(
                    name="t",
                    description="x",
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="int", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        service = SqlValidationService(catalog_provider=StaticSqlCatalogProvider(bad_catalog))
        result = service.validate("SELECT 1")
        assert any(e.code == "UNSUPPORTED_DIALECT" for e in result.errors)


# ── TestParserLimitations ────────────────────────────────────────────────────


class TestParserLimitations:
    """Parser limitation tests - documented cases where SQLGlot cannot parse valid PostgreSQL."""

    def test_delete_returning_in_cte_parse_limitation(self, validation_service):
        """DELETE ... RETURNING in CTE - parser limitation."""
        result = validation_service.validate(
            "WITH deleted AS (DELETE FROM orders RETURNING id) SELECT id FROM deleted"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_update_returning_in_cte_parse_limitation(self, validation_service):
        """UPDATE ... RETURNING in CTE - parser limitation."""
        result = validation_service.validate(
            "WITH changed AS (UPDATE orders SET total_cents = 0 RETURNING id) SELECT id FROM changed"
        )
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_select_for_update_parse_limitation(self, validation_service):
        """SELECT ... FOR UPDATE - parser limitation."""
        result = validation_service.validate("SELECT id FROM orders FOR UPDATE")
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_select_into_parse_limitation(self, validation_service):
        """SELECT ... INTO - parser limitation."""
        result = validation_service.validate("SELECT id INTO new_orders FROM orders")
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_copy_command_parse_limitation(self, validation_service):
        """COPY command - parser limitation."""
        result = validation_service.validate("COPY orders TO '/tmp/orders.csv'")
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)

    def test_call_statement_parse_limitation(self, validation_service):
        """CALL statement - parser limitation."""
        result = validation_service.validate("CALL my_proc()")
        assert result.valid is False
        assert any(e.code == "PARSE_ERROR" for e in result.errors)


# ── TestHarmlessAliases ──────────────────────────────────────────────────────


class TestHarmlessAliases:
    """Harmless aliases containing system-like text should be allowed."""

    def test_alias_with_pg_catalog_allowed(self, validation_service):
        """Alias containing 'pg_catalog' allowed."""
        result = validation_service.validate("SELECT 'pg_catalog' AS pg_catalog FROM customers")
        assert result.valid is True

    def test_alias_with_information_schema_allowed(self, validation_service):
        """Alias containing 'information_schema' allowed."""
        result = validation_service.validate("SELECT 'info' AS information_schema FROM customers")
        assert result.valid is True

    def test_alias_with_system_schema_allowed(self, validation_service):
        """Alias containing 'pg_toast' allowed."""
        result = validation_service.validate("SELECT 'toast' AS pg_toast FROM customers")
        assert result.valid is True

    def test_column_alias_with_system_name_allowed(self, validation_service):
        """Column alias with system-like name allowed."""
        result = validation_service.validate("SELECT id AS pg_catalog FROM customers")
        assert result.valid is True


# ── TestJoins ─────────────────────────────────────────────────────────────────


class TestJoins:
    """Join validation."""

    def test_inner_join_valid(self, validation_service):
        """INNER JOIN with qualified columns valid."""
        result = validation_service.validate(
            "SELECT o.id, c.name FROM orders o INNER JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is True

    def test_left_join_valid(self, validation_service):
        """LEFT JOIN with qualified columns valid."""
        result = validation_service.validate(
            "SELECT o.id, c.name FROM orders o LEFT JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is True

    def test_join_with_ambiguous_unqualified_rejected(self, validation_service):
        """JOIN with ambiguous unqualified column rejected."""
        result = validation_service.validate(
            "SELECT id FROM orders o JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is False
        assert any(e.code == "UNQUALIFIED_COLUMN_AMBIGUOUS" for e in result.errors)

    def test_join_with_qualified_columns_allowed(self, validation_service):
        """JOIN with qualified columns allowed."""
        result = validation_service.validate(
            "SELECT o.id, c.id FROM orders o JOIN customers c ON o.customer_id = c.id"
        )
        assert result.valid is True


# ── TestDialectHandling ──────────────────────────────────────────────────────


class TestDialectHandling:
    """Dialect mapping from catalog to SQLGlot."""

    def test_postgresql_dialect_mapped_to_postgres(self, validation_service):
        """postgresql catalog dialect maps to postgres SQLGlot dialect."""
        result = validation_service.validate("SELECT id FROM customers")
        assert result.valid is True

    def test_postgres_dialect_mapped_to_postgres(self):
        """postgres catalog dialect maps to postgres SQLGlot dialect."""
        from queryguard.contracts import SqlColumnDefinition, SqlSchemaCatalog, SqlTableDefinition

        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1",
            dialect="postgres",
            tables=(
                SqlTableDefinition(
                    name="t",
                    description="x",
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="int", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        service = SqlValidationService(catalog_provider=StaticSqlCatalogProvider(catalog))
        result = service.validate("SELECT id FROM t")
        assert result.valid is True
