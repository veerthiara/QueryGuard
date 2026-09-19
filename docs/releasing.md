# Releasing QueryGuard

QueryGuard is not configured to publish to PyPI yet. This document describes
the release preparation process for when a registry and publishing policy have
been chosen.

1. Ensure `main` is clean and contains the intended changes.
2. Run `make check`.
3. Update the package version and `CHANGELOG.md`.
4. Run `make build`.
5. Inspect the generated wheel and source distribution in `dist/`.
6. Run `python scripts/verify_package.py` to prove the wheel installs and
   imports in a clean virtual environment.
7. Create and verify a release tag according to the project's tag policy.
8. Publish only after the package registry, credentials, and release ownership
   have been explicitly decided.

Do not commit `dist/`, `build/`, coverage output, or environment caches. A
license choice is also required before a public release.
