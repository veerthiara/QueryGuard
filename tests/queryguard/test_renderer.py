"""Tests for generic prompt renderer."""

from queryguard.contracts import (
    SqlColumnDefinition,
    SqlRelationshipDefinition,
    SqlSchemaCatalog,
    SqlTableDefinition,
)
from queryguard.renderer import SqlSchemaContextRenderer, render_catalog_for_prompt


def _fake_catalog() -> SqlSchemaCatalog:
    return SqlSchemaCatalog(
        catalog_name="testapp",
        catalog_version="1.0",
        dialect="postgresql",
        tables=(
            SqlTableDefinition(
                name="customers",
                description="Customer accounts",
                user_scoped=False,
                columns=(
                    SqlColumnDefinition(
                        name="id",
                        description="Unique customer ID",
                        data_type="uuid",
                        is_primary_key=True,
                    ),
                    SqlColumnDefinition(
                        name="email",
                        description="Login email",
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
                business_rules=("Email must be unique",),
            ),
            SqlTableDefinition(
                name="orders",
                description="Customer orders",
                user_scoped=True,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="Order ID", data_type="uuid", is_primary_key=True
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
                        name="placed_at",
                        description="Order timestamp",
                        data_type="timestamp with time zone",
                        nullable=False,
                    ),
                    SqlColumnDefinition(
                        name="secret_note", description="Internal", data_type="text", sensitive=True
                    ),
                ),
                business_rules=("Only completed orders have total_cents > 0",),
            ),
            SqlTableDefinition(
                name="internal_logs",
                description="Internal audit logs",
                allowed_for_select=False,
                user_scoped=False,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="Log ID", data_type="uuid", is_primary_key=True
                    ),
                    SqlColumnDefinition(
                        name="action", description="Action taken", data_type="varchar(50)"
                    ),
                ),
            ),
        ),
        relationships=(
            SqlRelationshipDefinition(
                left_table="orders",
                left_column="customer_id",
                right_table="customers",
                right_column="id",
                relationship_type="many_to_one",
                description="Orders belong to customers",
            ),
        ),
        global_rules=(
            "Only SELECT statements allowed",
            "Always filter by user_id on user-scoped tables",
            "Use LIMIT (default 50, max 100)",
        ),
    )


class TestSqlSchemaContextRenderer:
    def test_includes_catalog_header(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "Database dialect: postgresql" in output
        assert "Catalog: testapp v1.0" in output

    def test_includes_selectable_tables_only(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "Table: customers" in output
        assert "Table: orders" in output
        assert "Table: internal_logs" not in output  # allowed_for_select=False

    def test_includes_table_descriptions(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "Purpose: Customer accounts." in output
        assert "Purpose: Customer orders." in output

    def test_includes_business_rules(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "Business rule: Email must be unique" in output
        assert "Business rule: Only completed orders have total_cents > 0" in output

    def test_includes_user_scope(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "User scoped: no" in output  # customers
        assert "User scoped: yes" in output  # orders

    def test_includes_selectable_columns_only(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "email" in output
        assert "total_cents" in output
        assert "secret_note" not in output  # sensitive

    def test_includes_column_metadata(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "primary key" in output
        assert "foreign key -> customers.id" in output
        assert "user scope" in output
        assert "not null" in output

    def test_includes_relationships(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "orders.customer_id -> customers.id (many-to-one)" in output

    def test_includes_global_rules(self):
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        assert "Global rules:" in output
        assert "Only SELECT statements allowed" in output
        assert "Use LIMIT" in output

    def test_deterministic_output(self):
        """Same catalog should always produce identical output."""
        renderer = SqlSchemaContextRenderer()
        output1 = renderer.render(_fake_catalog())
        output2 = renderer.render(_fake_catalog())
        assert output1 == output2

    def test_table_sorting(self):
        """Tables should be sorted by name for deterministic output."""
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="zebra",
                    description="Z",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="apple",
                    description="A",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="banana",
                    description="B",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(catalog)
        # Find positions of table headers
        apple_pos = output.find("Table: apple")
        banana_pos = output.find("Table: banana")
        zebra_pos = output.find("Table: zebra")
        assert apple_pos < banana_pos < zebra_pos

    def test_column_sorting(self):
        """Columns should be sorted by name within each table."""
        table = SqlTableDefinition(
            name="products",
            description="Product catalog",
            user_scoped=False,
            columns=(
                SqlColumnDefinition(name="z_field", description="Z", data_type="text"),
                SqlColumnDefinition(name="a_field", description="A", data_type="text"),
                SqlColumnDefinition(name="b_field", description="B", data_type="text"),
            ),
        )
        catalog = SqlSchemaCatalog(catalog_name="test", catalog_version="1.0", tables=(table,))
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(catalog)
        a_pos = output.find("a_field")
        b_pos = output.find("b_field")
        z_pos = output.find("z_field")
        assert a_pos < b_pos < z_pos

    def test_relationship_sorting(self):
        """Relationships should be sorted for deterministic output."""
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="a",
                    description="A",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="b",
                    description="B",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                        SqlColumnDefinition(
                            name="a_id",
                            description="FK",
                            data_type="uuid",
                            is_foreign_key=True,
                            foreign_key_target="a.id",
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="c",
                    description="C",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                        SqlColumnDefinition(
                            name="b_id",
                            description="FK",
                            data_type="uuid",
                            is_foreign_key=True,
                            foreign_key_target="b.id",
                        ),
                    ),
                ),
            ),
            relationships=(
                SqlRelationshipDefinition(
                    left_table="c",
                    left_column="b_id",
                    right_table="b",
                    right_column="id",
                    relationship_type="many_to_one",
                ),
                SqlRelationshipDefinition(
                    left_table="b",
                    left_column="a_id",
                    right_table="a",
                    right_column="id",
                    relationship_type="many_to_one",
                ),
            ),
        )
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(catalog)
        # b->a should appear before c->b
        ba_pos = output.find("b.a_id -> a.id")
        cb_pos = output.find("c.b_id -> b.id")
        assert ba_pos < cb_pos

    def test_excludes_non_selectable_tables_from_relationships(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="a",
                    description="x",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="b",
                    description="y",
                    allowed_for_select=False,
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
            relationships=(
                SqlRelationshipDefinition(
                    left_table="a",
                    left_column="id",
                    right_table="b",
                    right_column="id",
                    relationship_type="one_to_one",
                ),
            ),
        )
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(catalog)
        assert "a.id -> b.id" not in output

    def test_no_application_specific_names_in_output(self):
        """Generic renderer must not leak application-specific names."""
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(_fake_catalog())
        # These names belong to another application domain and must not leak.
        assert "habits" not in output
        assert "habit_logs" not in output
        assert "bottle_events" not in output
        assert "daily_summaries" not in output
        # Only fake domain names
        assert "customers" in output
        assert "orders" in output

    def test_hidden_table_fk_target_not_leaked_in_column_metadata(self):
        """When a column references a hidden table (allowed_for_select=False),
        the FK target should not be rendered in column metadata.
        The column can still show 'user scope' if is_user_scope=True.
        """
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="hidden_users",
                    description="Hidden user table",
                    user_scoped=False,
                    allowed_for_select=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="User ID", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="orders",
                    description="Orders",
                    user_scoped=True,
                    allowed_for_select=True,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="Order ID", data_type="uuid", is_primary_key=True
                        ),
                        SqlColumnDefinition(
                            name="user_id",
                            description="Owner user",
                            data_type="uuid",
                            is_foreign_key=True,
                            foreign_key_target="hidden_users.id",
                            is_user_scope=True,
                        ),
                        SqlColumnDefinition(
                            name="total", description="Total", data_type="integer", nullable=False
                        ),
                    ),
                ),
            ),
            relationships=(),
            global_rules=(),
        )
        renderer = SqlSchemaContextRenderer()
        output = renderer.render(catalog)

        # The orders table should be rendered
        assert "Table: orders" in output
        # The hidden_users table should NOT be rendered
        assert "Table: hidden_users" not in output

        # The user_id column should be rendered with "user scope" but NOT "foreign key -> hidden_users.id"
        assert "user_id" in output
        assert "user scope" in output
        assert "foreign key -> hidden_users.id" not in output
        # The FK target table name should not appear anywhere in output
        assert "hidden_users" not in output

        # The relationship section should be empty (no relationships between selectable tables)
        assert "Relationships:" not in output


class TestRenderCatalogForPromptCompat:
    def test_backward_compat_function(self):
        output = render_catalog_for_prompt(_fake_catalog())
        assert "Database dialect: postgresql" in output
        assert "Catalog: testapp v1.0" in output
