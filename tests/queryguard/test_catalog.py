"""Tests for generic catalog provider."""

import pytest

from queryguard.catalog import (
    LazySqlCatalogProvider,
    SqlCatalogProvider,
    StaticSqlCatalogProvider,
)
from queryguard.contracts import SqlColumnDefinition, SqlSchemaCatalog, SqlTableDefinition


class TestSqlCatalogProvider:
    def test_protocol_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            SqlCatalogProvider()


class TestStaticSqlCatalogProvider:
    def test_returns_catalog(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="t",
                    description="x",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        provider = StaticSqlCatalogProvider(catalog)
        assert provider.get_catalog() is catalog

    def test_multiple_calls_return_same(self):
        catalog = SqlSchemaCatalog(
            catalog_name="test",
            catalog_version="1.0",
            tables=(
                SqlTableDefinition(
                    name="t",
                    description="x",
                    user_scoped=False,
                    columns=(
                        SqlColumnDefinition(
                            name="id", description="x", data_type="uuid", is_primary_key=True
                        ),
                    ),
                ),
            ),
        )
        provider = StaticSqlCatalogProvider(catalog)
        assert provider.get_catalog() is provider.get_catalog()


class TestLazySqlCatalogProvider:
    def test_builds_on_first_call(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return SqlSchemaCatalog(
                catalog_name="test",
                catalog_version="1.0",
                tables=(
                    SqlTableDefinition(
                        name="t",
                        description="x",
                        user_scoped=False,
                        columns=(
                            SqlColumnDefinition(
                                name="id", description="x", data_type="uuid", is_primary_key=True
                            ),
                        ),
                    ),
                ),
            )

        provider = LazySqlCatalogProvider(factory)
        assert call_count == 0

        c1 = provider.get_catalog()
        assert call_count == 1

        c2 = provider.get_catalog()
        assert call_count == 1  # cached
        assert c1 is c2

    def test_factory_exception_propagates(self):
        def failing_factory():
            raise RuntimeError("build failed")

        provider = LazySqlCatalogProvider(failing_factory)
        with pytest.raises(RuntimeError, match="build failed"):
            provider.get_catalog()
