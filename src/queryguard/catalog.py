"""Catalog provider abstractions for application-supplied schema catalogs."""

from collections.abc import Callable
from typing import Protocol

from queryguard.contracts import SqlSchemaCatalog


class SqlCatalogProvider(Protocol):
    """Provide the approved schema catalog for one application."""

    def get_catalog(self) -> SqlSchemaCatalog:
        """Return the complete approved catalog."""
        ...


class StaticSqlCatalogProvider:
    """A provider that returns one pre-built catalog."""

    def __init__(self, catalog: SqlSchemaCatalog) -> None:
        self._catalog = catalog

    def get_catalog(self) -> SqlSchemaCatalog:
        return self._catalog


class LazySqlCatalogProvider:
    """A provider that constructs its catalog on first access."""

    def __init__(self, factory: Callable[[], SqlSchemaCatalog]) -> None:
        self._factory = factory
        self._catalog: SqlSchemaCatalog | None = None

    def get_catalog(self) -> SqlSchemaCatalog:
        if self._catalog is None:
            self._catalog = self._factory()
        return self._catalog
