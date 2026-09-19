"""High-level generation and validation facade for QueryGuard."""

from __future__ import annotations

from pathlib import Path

from queryguard.catalog import SqlCatalogProvider, StaticSqlCatalogProvider
from queryguard.contracts import (
    QueryPreparationResult,
    SqlPolicyValidationResult,
    SqlValidationResult,
)
from queryguard.generation import SqlGenerationProvider, SqlGenerationService
from queryguard.policy import SqlPolicyValidationService
from queryguard.settings import SqlAnalyticsSettings
from queryguard.validation import SqlValidationService
from queryguard.yaml_loader import load_catalog_from_yaml


class QueryGuard:
    """Compose generation, structural validation, and policy validation only."""

    def __init__(
        self,
        catalog_provider: SqlCatalogProvider,
        generation_provider: SqlGenerationProvider,
        settings: SqlAnalyticsSettings | None = None,
    ) -> None:
        self._settings = settings or SqlAnalyticsSettings()
        self._generation_service = SqlGenerationService(
            catalog_provider=catalog_provider,
            provider=generation_provider,
            settings=self._settings,
        )
        self._structural_validator = SqlValidationService(catalog_provider)
        self._policy_validator = SqlPolicyValidationService(
            catalog_provider=catalog_provider,
            settings=self._settings,
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        provider: SqlGenerationProvider,
        settings: SqlAnalyticsSettings | None = None,
    ) -> "QueryGuard":
        """Build a facade from an application-owned YAML catalog."""

        catalog = load_catalog_from_yaml(path)
        return cls(
            catalog_provider=StaticSqlCatalogProvider(catalog),
            generation_provider=provider,
            settings=settings,
        )

    async def prepare(
        self,
        question: str,
        *,
        conversation_history: tuple[dict[str, str], ...] = (),
    ) -> QueryPreparationResult:
        """Generate SQL and stop at the first failed validation stage."""

        try:
            generated = await self._generation_service.generate(
                question,
                conversation_history=conversation_history,
            )
        except Exception as exc:
            return QueryPreparationResult(
                approved=False,
                stage="generation",
                errors=(str(exc),),
            )

        return self._validate_generated(generated)

    def validate_sql(self, sql: str) -> QueryPreparationResult:
        """Validate caller-supplied SQL without invoking the generation provider."""

        structural = self._structural_validator.validate(sql)
        if not structural.valid:
            return QueryPreparationResult(
                approved=False,
                structural=structural,
                stage="structural_validation",
                errors=_structural_errors(structural),
            )
        policy = self._policy_validator.validate(sql)
        if not policy.valid:
            return QueryPreparationResult(
                approved=False,
                structural=structural,
                policy=policy,
                stage="policy_validation",
                errors=_policy_errors(policy),
            )
        return QueryPreparationResult(
            approved=True,
            structural=structural,
            policy=policy,
            stage="approved",
        )

    def _validate_generated(self, generated) -> QueryPreparationResult:
        structural = self._structural_validator.validate(generated)
        if not structural.valid:
            return QueryPreparationResult(
                approved=False,
                generated=generated,
                structural=structural,
                stage="structural_validation",
                errors=_structural_errors(structural),
            )
        policy = self._policy_validator.validate(generated.sql)
        if not policy.valid:
            return QueryPreparationResult(
                approved=False,
                generated=generated,
                structural=structural,
                policy=policy,
                stage="policy_validation",
                errors=_policy_errors(policy),
            )
        return QueryPreparationResult(
            approved=True,
            generated=generated,
            structural=structural,
            policy=policy,
            stage="approved",
        )


def _structural_errors(result: SqlValidationResult) -> tuple[str, ...]:
    return tuple(f"{error.code}: {error.message}" for error in result.errors)


def _policy_errors(result: SqlPolicyValidationResult) -> tuple[str, ...]:
    return tuple(f"{error.code}: {error.message}" for error in result.errors)
