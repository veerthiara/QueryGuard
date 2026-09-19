"""Tests for strict, safe YAML catalog loading."""

from pathlib import Path

import pytest

from queryguard import CatalogYamlError, load_catalog_from_yaml, parse_catalog_yaml


EXAMPLE_PATH = Path(__file__).parents[2] / "examples" / "commerce_catalog.yaml"

VALID_YAML = """
catalog:
  name: test_catalog
  version: "1"
tables:
  - name: customers
    description: Customers
    columns:
      - name: id
        description: Customer ID
        type: uuid
        primary_key: true
"""


def test_valid_example_loads():
    assert load_catalog_from_yaml(EXAMPLE_PATH).catalog_name == "commerce"


def test_catalog_metadata_maps_correctly():
    catalog = load_catalog_from_yaml(EXAMPLE_PATH)
    assert (catalog.catalog_name, catalog.catalog_version, catalog.dialect) == ("commerce", "1.0", "postgresql")


def test_table_metadata_maps_correctly():
    table = load_catalog_from_yaml(EXAMPLE_PATH).get_table("orders")
    assert table.description == "Customer orders"
    assert table.allowed_for_select is True


def test_column_metadata_maps_correctly():
    column = load_catalog_from_yaml(EXAMPLE_PATH).get_table("orders").get_column("customer_id")
    assert column is not None
    assert column.data_type == "uuid"
    assert column.is_foreign_key is True
    assert column.foreign_key_target == "customers.id"


def test_relationships_map_correctly():
    relationship = load_catalog_from_yaml(EXAMPLE_PATH).relationships[0]
    assert (relationship.left_table, relationship.right_table, relationship.relationship_type) == (
        "orders",
        "customers",
        "many_to_one",
    )


def test_aliases_map_correctly():
    assert load_catalog_from_yaml(EXAMPLE_PATH).get_table("customers").aliases == ("customer_accounts",)


def test_business_rules_map_correctly():
    assert load_catalog_from_yaml(EXAMPLE_PATH).get_table("orders").business_rules == (
        "Order totals are stored in cents.",
    )


def test_global_rules_map_correctly():
    assert load_catalog_from_yaml(EXAMPLE_PATH).global_rules == (
        "Only SELECT statements are permitted.",
        "User-scoped tables must be filtered by the application user parameter.",
    )


def test_user_scoped_metadata_maps_correctly():
    table = load_catalog_from_yaml(EXAMPLE_PATH).get_table("orders")
    assert table.user_scoped is True
    assert table.scope_strategy == "direct"
    assert table.user_scope_columns()[0].name == "account_id"


def test_path_input_works(tmp_path: Path):
    path = tmp_path / "catalog.yaml"
    path.write_text(VALID_YAML, encoding="utf-8")
    assert load_catalog_from_yaml(path).catalog_name == "test_catalog"


def test_string_path_input_works(tmp_path: Path):
    path = tmp_path / "catalog.yaml"
    path.write_text(VALID_YAML, encoding="utf-8")
    assert load_catalog_from_yaml(str(path)).catalog_name == "test_catalog"


def test_parse_catalog_yaml_works():
    assert parse_catalog_yaml(VALID_YAML).catalog_version == "1"


def test_malformed_yaml_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="invalid YAML syntax"):
        parse_catalog_yaml("catalog: [")


@pytest.mark.parametrize("content", ["", "  \n\t"])
def test_empty_or_whitespace_yaml_raises_catalog_yaml_error(content: str):
    with pytest.raises(CatalogYamlError, match="empty"):
        parse_catalog_yaml(content)


def test_root_list_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="root must be a mapping"):
        parse_catalog_yaml("- catalog")


def test_missing_catalog_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="missing required 'catalog'"):
        parse_catalog_yaml("tables: []")


def test_missing_tables_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="missing required 'tables'"):
        parse_catalog_yaml("catalog: {name: test, version: '1'}")


def test_invalid_field_type_raises_catalog_yaml_error():
    content = VALID_YAML.replace("        primary_key: true", "        nullable: not_a_boolean")
    with pytest.raises(CatalogYamlError, match="catalog validation failed"):
        parse_catalog_yaml(content)


def test_unknown_top_level_key_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="unknown key.*top level"):
        parse_catalog_yaml(f"{VALID_YAML}\nnot_a_catalog_key: true")


def test_unknown_table_key_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="unknown key.*tables\\[0\\]"):
        parse_catalog_yaml(VALID_YAML.replace("    columns:", "    misspelled_table_key: true\n    columns:"))


def test_unknown_column_key_raises_catalog_yaml_error():
    with pytest.raises(CatalogYamlError, match="unknown key.*columns"):
        parse_catalog_yaml(VALID_YAML.replace("        primary_key: true", "        primay_key: true"))


def test_unknown_relationship_key_raises_catalog_yaml_error():
    content = f"""{VALID_YAML}
relationships:
  - left_table: customers
    left_column: id
    right_table: customers
    right_column: id
    relationship_typ: one_to_one
"""
    with pytest.raises(CatalogYamlError, match="unknown key.*relationships"):
        parse_catalog_yaml(content)


def test_foreign_key_without_target_raises_catalog_yaml_error():
    content = VALID_YAML.replace("        primary_key: true", "        foreign_key: true")
    with pytest.raises(CatalogYamlError, match="foreign_key_target required"):
        parse_catalog_yaml(content)


def test_direct_user_scoped_table_without_scope_column_raises_catalog_yaml_error():
    content = VALID_YAML.replace("    columns:", "    user_scoped: true\n    columns:")
    with pytest.raises(CatalogYamlError, match="requires at least one"):
        parse_catalog_yaml(content)


def test_duplicate_table_raises_catalog_yaml_error():
    content = VALID_YAML + VALID_YAML.split("tables:\n", maxsplit=1)[1]
    with pytest.raises(CatalogYamlError, match="table names must be unique"):
        parse_catalog_yaml(content)


def test_duplicate_column_raises_catalog_yaml_error():
    content = VALID_YAML.replace(
        "        primary_key: true",
        "        primary_key: true\n      - name: id\n        description: Duplicate ID\n        type: uuid",
    )
    with pytest.raises(CatalogYamlError, match="column names must be unique"):
        parse_catalog_yaml(content)


def test_unsafe_python_object_tag_is_rejected():
    with pytest.raises(CatalogYamlError, match="invalid YAML syntax"):
        parse_catalog_yaml("!!python/object/apply:os.system ['echo unsafe']")
