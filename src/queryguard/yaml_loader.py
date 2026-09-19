"""Safe, strict YAML loading for application-owned QueryGuard catalogs."""

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from queryguard.contracts import SqlSchemaCatalog


class CatalogYamlError(ValueError):
    """Raised when a YAML catalog cannot be read, parsed, or validated."""


_TOP_LEVEL_KEYS = frozenset({"catalog", "tables", "relationships", "global_rules"})
_CATALOG_KEYS = frozenset({"name", "version", "dialect"})
_TABLE_KEYS = frozenset(
    {
        "name",
        "description",
        "columns",
        "user_scoped",
        "allowed_for_select",
        "aliases",
        "business_rules",
        "scope_strategy",
        "scope_description",
    }
)
_COLUMN_KEYS = frozenset(
    {
        "name",
        "description",
        "type",
        "nullable",
        "primary_key",
        "foreign_key",
        "foreign_key_target",
        "user_scope",
        "allowed_for_select",
        "sensitive",
    }
)
_RELATIONSHIP_KEYS = frozenset(
    {
        "left_table",
        "left_column",
        "right_table",
        "right_column",
        "relationship_type",
        "description",
    }
)


def load_catalog_from_yaml(path: str | Path) -> SqlSchemaCatalog:
    """Load a :class:`SqlSchemaCatalog` from a UTF-8 YAML file."""

    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, TypeError) as exc:
        raise CatalogYamlError(f"unable to read catalog YAML file: {path!s}") from exc
    return parse_catalog_yaml(content)


def parse_catalog_yaml(content: str) -> SqlSchemaCatalog:
    """Parse already-loaded YAML text into a validated schema catalog."""

    if not isinstance(content, str):
        raise CatalogYamlError("catalog YAML content must be text")
    if not content.strip():
        raise CatalogYamlError("catalog YAML is empty")

    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise CatalogYamlError("invalid YAML syntax") from exc

    if document is None:
        raise CatalogYamlError("catalog YAML is empty")
    if not isinstance(document, Mapping):
        raise CatalogYamlError("catalog YAML root must be a mapping")

    _validate_known_keys(document, _TOP_LEVEL_KEYS, "top level")
    if "catalog" not in document:
        raise CatalogYamlError("catalog YAML is missing required 'catalog' section")
    if "tables" not in document:
        raise CatalogYamlError("catalog YAML is missing required 'tables' section")

    catalog_section = _require_mapping(document["catalog"], "catalog")
    _validate_known_keys(catalog_section, _CATALOG_KEYS, "catalog")
    tables_section = _require_list(document["tables"], "tables")
    relationships_section = _require_list(document.get("relationships", []), "relationships")
    global_rules = _require_list(document.get("global_rules", []), "global_rules")

    catalog_data = _map_catalog(catalog_section)
    catalog_data["tables"] = tuple(
        _map_table(_require_mapping(table, f"tables[{index}]"), index)
        for index, table in enumerate(tables_section)
    )
    if "relationships" in document:
        catalog_data["relationships"] = tuple(
            _map_relationship(_require_mapping(relationship, f"relationships[{index}]"), index)
            for index, relationship in enumerate(relationships_section)
        )
    if "global_rules" in document:
        catalog_data["global_rules"] = global_rules

    try:
        return SqlSchemaCatalog.model_validate(catalog_data)
    except ValidationError as exc:
        raise CatalogYamlError(
            f"catalog validation failed: {_format_validation_error(exc)}"
        ) from exc


def _map_catalog(section: Mapping[object, object]) -> dict[str, object]:
    mapping = {"name": "catalog_name", "version": "catalog_version", "dialect": "dialect"}
    return {target: section[source] for source, target in mapping.items() if source in section}


def _map_table(section: Mapping[object, object], index: int) -> dict[str, object]:
    _validate_known_keys(section, _TABLE_KEYS, f"tables[{index}]")
    columns = _require_list(section.get("columns"), f"tables[{index}].columns")
    table = {key: section[key] for key in _TABLE_KEYS - {"columns"} if key in section}
    table["columns"] = tuple(
        _map_column(
            _require_mapping(column, f"tables[{index}].columns[{column_index}]"),
            index,
            column_index,
        )
        for column_index, column in enumerate(columns)
    )
    return table


def _map_column(
    section: Mapping[object, object], table_index: int, column_index: int
) -> dict[str, object]:
    context = f"tables[{table_index}].columns[{column_index}]"
    _validate_known_keys(section, _COLUMN_KEYS, context)
    mapping = {
        "name": "name",
        "description": "description",
        "type": "data_type",
        "nullable": "nullable",
        "primary_key": "is_primary_key",
        "foreign_key": "is_foreign_key",
        "foreign_key_target": "foreign_key_target",
        "user_scope": "is_user_scope",
        "allowed_for_select": "allowed_for_select",
        "sensitive": "sensitive",
    }
    return {target: section[source] for source, target in mapping.items() if source in section}


def _map_relationship(section: Mapping[object, object], index: int) -> dict[str, object]:
    _validate_known_keys(section, _RELATIONSHIP_KEYS, f"relationships[{index}]")
    return {key: value for key, value in section.items() if isinstance(key, str)}


def _require_mapping(value: object, context: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise CatalogYamlError(f"{context} must be a mapping")
    return value


def _require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise CatalogYamlError(f"{context} must be a list")
    return value


def _validate_known_keys(
    value: Mapping[object, object], allowed_keys: frozenset[str], context: str
) -> None:
    unknown_keys = [repr(key) for key in value if key not in allowed_keys]
    if unknown_keys:
        raise CatalogYamlError(f"unknown key(s) in {context}: {', '.join(unknown_keys)}")


def _format_validation_error(error: ValidationError) -> str:
    messages = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"])
        messages.append(f"{location}: {detail['msg']}")
    return "; ".join(messages)
