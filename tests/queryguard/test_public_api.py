"""Regression tests for documented QueryGuard package imports and metadata."""

from importlib.metadata import version

import queryguard
from queryguard import (
    GeneratedSql,
    QueryGuard,
    SqlPolicyValidationService,
    SqlValidationService,
    load_catalog_from_yaml,
)


def test_documented_top_level_public_api_is_available():
    assert QueryGuard is not None
    assert GeneratedSql is not None
    assert SqlValidationService is not None
    assert SqlPolicyValidationService is not None
    assert load_catalog_from_yaml is not None


def test_package_version_matches_installed_distribution_metadata():
    assert queryguard.__version__ == version("queryguard")
