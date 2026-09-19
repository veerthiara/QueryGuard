"""Tests for generic SQL analytics contracts."""

import pytest

from queryguard.contracts import (
    GeneratedSql,
    SqlColumnDefinition,
    SqlRelationshipDefinition,
    SqlSchemaCatalog,
    SqlTableDefinition,
)


class TestSqlColumnDefinition:
    def test_valid_column(self):
        col = SqlColumnDefinition(
            name="id",
            description="Primary key",
            data_type="uuid",
            is_primary_key=True,
        )
        assert col.name == "id"
        assert col.is_primary_key is True

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            SqlColumnDefinition(name="", description="x", data_type="uuid")

    def test_empty_description_raises(self):
        with pytest.raises(ValueError):
            SqlColumnDefinition(name="id", description="", data_type="uuid")

    def test_empty_data_type_raises(self):
        with pytest.raises(ValueError):
            SqlColumnDefinition(name="id", description="x", data_type="")

    def test_fk_requires_target(self):
        with pytest.raises(ValueError):
            SqlColumnDefinition(
                name="user_id", description="x", data_type="uuid", is_foreign_key=True
            )

    def test_fk_with_target_ok(self):
        col = SqlColumnDefinition(
            name="user_id",
            description="Owner",
            data_type="uuid",
            is_foreign_key=True,
            foreign_key_target="users.id",
        )
        assert col.foreign_key_target == "users.id"

    def test_sensitive_forces_allowed_for_select_false(self):
        col = SqlColumnDefinition(
            name="secret",
            description="Hidden",
            data_type="text",
            sensitive=True,
            allowed_for_select=True,  # Should be auto-corrected
        )
        assert col.allowed_for_select is False

    def test_sensitive_explicit_false_allowed(self):
        col = SqlColumnDefinition(
            name="secret",
            description="Hidden",
            data_type="text",
            sensitive=True,
            allowed_for_select=False,
        )
        assert col.allowed_for_select is False


class TestSqlTableDefinition:
    def test_valid_table(self):
        table = SqlTableDefinition(
            name="users",
            description="App users",
            user_scoped=False,
            columns=(
                SqlColumnDefinition(
                    name="id", description="PK", data_type="uuid", is_primary_key=True
                ),
            ),
        )
        assert table.name == "users"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            SqlTableDefinition(name="", description="x", user_scoped=False, columns=())

    def test_no_columns_raises(self):
        with pytest.raises(ValueError):
            SqlTableDefinition(name="t", description="x", user_scoped=False, columns=())

    def test_duplicate_column_names_raises(self):
        with pytest.raises(ValueError):
            SqlTableDefinition(
                name="t",
                description="x",
                user_scoped=False,
                columns=(
                    SqlColumnDefinition(name="id", description="a", data_type="uuid"),
                    SqlColumnDefinition(name="id", description="b", data_type="text"),
                ),
            )

    def test_user_scoped_requires_scope_column_direct(self):
        with pytest.raises(ValueError):
            SqlTableDefinition(
                name="t",
                description="x",
                user_scoped=True,
                columns=(
                    SqlColumnDefinition(
                        name="id", description="PK", data_type="uuid", is_primary_key=True
                    ),
                ),
            )

    def test_user_scoped_with_scope_column_ok(self):
        table = SqlTableDefinition(
            name="t",
            description="x",
            user_scoped=True,
            columns=(
                SqlColumnDefinition(
                    name="id", description="PK", data_type="uuid", is_primary_key=True
                ),
                SqlColumnDefinition(
                    name="user_id", description="Owner", data_type="uuid", is_user_scope=True
                ),
            ),
        )
        assert table.user_scoped is True

    def test_selectable_columns_excludes_sensitive(self):
        table = SqlTableDefinition(
            name="t",
            description="x",
            user_scoped=False,
            columns=(
                SqlColumnDefinition(
                    name="id", description="PK", data_type="uuid", is_primary_key=True
                ),
                SqlColumnDefinition(
                    name="secret", description="Hidden", data_type="text", sensitive=True
                ),
            ),
        )
        selectable = table.selectable_columns()
        assert len(selectable) == 1
        assert selectable[0].name == "id"

    def test_user_scope_columns_returns_scoped(self):
        table = SqlTableDefinition(
            name="t",
            description="x",
            user_scoped=True,
            columns=(
                SqlColumnDefinition(
                    name="id", description="PK", data_type="uuid", is_primary_key=True
                ),
                SqlColumnDefinition(
                    name="user_id", description="Owner", data_type="uuid", is_user_scope=True
                ),
            ),
        )
        scoped = table.user_scope_columns()
        assert len(scoped) == 1
        assert scoped[0].name == "user_id"

    def test_primary_keys_property(self):
        table = SqlTableDefinition(
            name="t",
            description="x",
            user_scoped=False,
            columns=(
                SqlColumnDefinition(
                    name="id", description="PK", data_type="uuid", is_primary_key=True
                ),
                SqlColumnDefinition(
                    name="other_id", description="Other PK", data_type="uuid", is_primary_key=True
                ),
                SqlColumnDefinition(name="col", description="Not PK", data_type="text"),
            ),
        )
        assert set(table.primary_keys) == {"id", "other_id"}


class TestSqlRelationshipDefinition:
    def test_valid_relationship(self):
        rel = SqlRelationshipDefinition(
            left_table="orders",
            left_column="customer_id",
            right_table="customers",
            right_column="id",
            relationship_type="many_to_one",
        )
        assert rel.relationship_type == "many_to_one"

    def test_invalid_relationship_type_raises(self):
        with pytest.raises(ValueError):
            SqlRelationshipDefinition(
                left_table="a",
                left_column="x",
                right_table="b",
                right_column="y",
                relationship_type="invalid",
            )

    def test_identical_refs_raises(self):
        with pytest.raises(ValueError):
            SqlRelationshipDefinition(
                left_table="t",
                left_column="id",
                right_table="t",
                right_column="id",
                relationship_type="one_to_one",
            )


class TestSqlSchemaCatalog:
    def test_valid_catalog(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="users",
                    description="Users",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        assert catalog.catalog_name == "test"

    def test_no_tables_raises(self):
        with pytest.raises(ValueError):
            SqlSchemaCatalog(catalog_name="test", catalog_version="1.0", tables=())

    def test_duplicate_table_names_raises(self):
        with pytest.raises(ValueError):
            SqlSchemaCatalog(
                catalog_name="test",
                catalog_version="1.0",
                tables=(
                    SqlTableDefinition(
                        name="t",
                        description="a",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="x", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                    SqlTableDefinition(
                        name="t",
                        description="b",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="x", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                ),
            )

    def test_relationship_unknown_table_raises(self):
        with pytest.raises(ValueError):
            SqlSchemaCatalog(
                catalog_name="test",
                catalog_version="1.0",
                tables=(
                    SqlTableDefinition(
                        name="users",
                        description="Users",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="PK", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                ),
                relationships=(
                    SqlRelationshipDefinition(
                        left_table="orders",
                        left_column="user_id",
                        right_table="users",
                        right_column="id",
                        relationship_type="many_to_one",
                    ),
                ),
            )

    def test_relationship_unknown_column_raises(self):
        with pytest.raises(ValueError):
            SqlSchemaCatalog(
                catalog_name="test",
                catalog_version="1.0",
                tables=(
                    SqlTableDefinition(
                        name="users",
                        description="Users",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="PK", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                    SqlTableDefinition(
                        name="orders",
                        description="Orders",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="PK", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                ),
                relationships=(
                    SqlRelationshipDefinition(
                        left_table="orders",
                        left_column="missing_col",
                        right_table="users",
                        right_column="id",
                        relationship_type="many_to_one",
                    ),
                ),
            )

    def test_duplicate_relationship_raises(self):
        with pytest.raises(ValueError):
            SqlSchemaCatalog(
                catalog_name="test",
                catalog_version="1.0",
                tables=(
                    SqlTableDefinition(
                        name="users",
                        description="Users",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="PK", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                    SqlTableDefinition(
                        name="orders",
                        description="Orders",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="PK", data_type="uuid", is_primary_key=True
                            ),
                            SqlColumnDefinition(name="user_id", description="FK", data_type="uuid"),
                        ),
                    ),
                ),
                relationships=(
                    SqlRelationshipDefinition(
                        left_table="orders",
                        left_column="user_id",
                        right_table="users",
                        right_column="id",
                        relationship_type="many_to_one",
                    ),
                    SqlRelationshipDefinition(
                        left_table="orders",
                        left_column="user_id",
                        right_table="users",
                        right_column="id",
                        relationship_type="many_to_one",
                    ),
                ),
            )

    def test_get_table_raises_keyerror(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="users",
                    description="Users",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        with pytest.raises(KeyError):
            catalog.get_table("missing")

    def test_allowed_table_names(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="users",
                    description="Users",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="internal",
                    description="Internal",
                    allowed_for_select=False,
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        assert catalog.allowed_table_names() == frozenset({"users"})

    def test_allowed_columns(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="users",
                    description="Users",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                        SqlColumnDefinition(
                            name="secret", description="Hidden", data_type="text", sensitive=True
                        ),
                    ),
                ),
            ),
        )
        assert catalog.allowed_columns("users") == frozenset({"id"})

    def test_user_scope_columns(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="orders",
                    description="Orders",
                    user_scoped=True,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                        SqlColumnDefinition(
                            name="user_id",
                            description="Owner",
                            data_type="uuid",
                            is_user_scope=True,
                        ),
                    ),
                ),
            ),
        )
        assert catalog.user_scope_columns("orders") == frozenset({"user_id"})

    def test_get_relationships_for_table(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="users",
                    description="Users",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
                SqlTableDefinition(
                    name="orders",
                    description="Orders",
                    user_scoped=True,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="PK", data_type="uuid", is_primary_key=True
                        ),
                        SqlColumnDefinition(
                            name="user_id",
                            description="FK",
                            data_type="uuid",
                            is_user_scope=True,
                            is_foreign_key=True,
                            foreign_key_target="users.id",
                        ),
                    ),
                ),
            ),
            relationships=(
                SqlRelationshipDefinition(
                    left_table="orders",
                    left_column="user_id",
                    right_table="users",
                    right_column="id",
                    relationship_type="many_to_one",
                ),
            ),
        )
        rels = catalog.get_relationships_for_table("orders")
        assert len(rels) == 1
        assert rels[0].left_table == "orders"


class TestGeneratedSql:
    def test_valid_generated_sql(self):
        gen = GeneratedSql(
            sql="SELECT * FROM users",
            referenced_tables=("users",),
            referenced_columns=("id",),
            explanation="Get all users",
            confidence=0.95,
        )
        assert gen.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            GeneratedSql(sql="SELECT 1", confidence=1.5)
        with pytest.raises(ValueError):
            GeneratedSql(sql="SELECT 1", confidence=-0.1)

    def test_empty_sql_raises(self):
        with pytest.raises(ValueError):
            GeneratedSql(sql="")
