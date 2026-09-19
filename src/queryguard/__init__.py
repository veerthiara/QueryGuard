"""QueryGuard: reusable structural safeguards for SQL analytics."""

from queryguard.catalog import (
    LazySqlCatalogProvider,
    SqlCatalogProvider,
    StaticSqlCatalogProvider,
)
from queryguard.contracts import (
    GeneratedSql,
    SqlColumnDefinition,
    SqlRelationshipDefinition,
    SqlSchemaCatalog,
    SqlTableDefinition,
    SqlValidationError,
    SqlValidationResult,
)
from queryguard.renderer import SqlSchemaContextRenderer, render_catalog_for_prompt
from queryguard.settings import SqlAnalyticsSettings
from queryguard.validation import SqlValidationService
from queryguard.yaml_loader import CatalogYamlError, load_catalog_from_yaml, parse_catalog_yaml

__version__ = "0.2.0"

__all__ = [
    "GeneratedSql",
    "CatalogYamlError",
    "LazySqlCatalogProvider",
    "SqlAnalyticsSettings",
    "SqlCatalogProvider",
    "SqlColumnDefinition",
    "SqlRelationshipDefinition",
    "SqlSchemaCatalog",
    "SqlSchemaContextRenderer",
    "SqlTableDefinition",
    "SqlValidationError",
    "SqlValidationResult",
    "SqlValidationService",
    "StaticSqlCatalogProvider",
    "render_catalog_for_prompt",
    "load_catalog_from_yaml",
    "parse_catalog_yaml",
]
