"""QueryGuard: reusable structural safeguards for SQL analytics."""

from queryguard.catalog import (
    LazySqlCatalogProvider,
    SqlCatalogProvider,
    StaticSqlCatalogProvider,
)
from queryguard.contracts import (
    GeneratedSql,
    QueryPreparationResult,
    SqlColumnDefinition,
    SqlPolicyError,
    SqlPolicyValidationResult,
    SqlRelationshipDefinition,
    SqlSchemaCatalog,
    SqlTableDefinition,
    SqlValidationError,
    SqlValidationResult,
)
from queryguard.facade import QueryGuard
from queryguard.generation import (
    SqlGenerationError,
    SqlGenerationProvider,
    SqlGenerationResponseError,
    SqlGenerationService,
)
from queryguard.policy import SqlPolicyValidationService
from queryguard.prompts import build_sql_generation_messages
from queryguard.renderer import SqlSchemaContextRenderer, render_catalog_for_prompt
from queryguard.settings import SqlAnalyticsSettings
from queryguard.validation import SqlValidationService
from queryguard.yaml_loader import CatalogYamlError, load_catalog_from_yaml, parse_catalog_yaml

__version__ = "0.10.0"

__all__ = [
    "GeneratedSql",
    "QueryGuard",
    "QueryPreparationResult",
    "CatalogYamlError",
    "LazySqlCatalogProvider",
    "SqlAnalyticsSettings",
    "SqlCatalogProvider",
    "SqlColumnDefinition",
    "SqlGenerationError",
    "SqlGenerationProvider",
    "SqlGenerationResponseError",
    "SqlGenerationService",
    "SqlPolicyError",
    "SqlPolicyValidationResult",
    "SqlPolicyValidationService",
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
    "build_sql_generation_messages",
]
