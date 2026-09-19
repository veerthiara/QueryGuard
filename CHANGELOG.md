# Changelog

This changelog records package milestones. Release dates are intentionally not
listed because they are not tracked in this repository.

## 0.9.0

- Hardened packaging metadata and development extras.
- Added Ruff, mypy, coverage, Make targets, CI, contributor guidance, release
  documentation, and built-wheel clean-install verification.

## 0.8.0

- Added a deterministic end-to-end acceptance suite using the commerce YAML
  catalog and test-only generation providers.

## 0.7.0

- Added the unified `QueryGuard` facade for generation, structural validation,
  policy validation, and result preparation.

## 0.6.0

- Extracted database execution from QueryGuard core into a separate companion
  boundary. The core package again ends at approved SQL.

## 0.5.0

- Added a historical optional read-only SQL execution adapter. This adapter was
  subsequently removed from core in 0.6.0 so execution could be maintained as
  a separate concern.

## 0.4.0

- Added policy validation for user scope and result bounds.

## 0.3.0

- Added provider-neutral, single-pass SQL generation.

## 0.2.0

- Added safe, strict YAML catalog loading.

## 0.1.0

- Established the standalone schema catalog and SQL structural-validation core.
