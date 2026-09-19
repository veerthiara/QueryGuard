"""Verify that a built QueryGuard wheel installs and works outside the source tree."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DIST_DIRECTORY = REPOSITORY_ROOT / "dist"
EXAMPLE_CATALOG = REPOSITORY_ROOT / "examples" / "commerce_catalog.yaml"


def _venv_python(venv_directory: Path) -> Path:
    if os.name == "nt":
        return venv_directory / "Scripts" / "python.exe"
    return venv_directory / "bin" / "python"


def _wheel_path() -> Path:
    wheels = sorted(DIST_DIRECTORY.glob("queryguard-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(
            "Expected exactly one QueryGuard wheel in dist/. Run `python -m build` first."
        )
    return wheels[0]


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    wheel = _wheel_path()
    if not EXAMPLE_CATALOG.is_file():
        raise SystemExit(f"Example catalog is missing: {EXAMPLE_CATALOG}")

    with tempfile.TemporaryDirectory(prefix="queryguard-wheel-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        venv_directory = temporary_path / "venv"
        _run([sys.executable, "-m", "venv", str(venv_directory)], cwd=temporary_path)
        python = _venv_python(venv_directory)
        _run([str(python), "-m", "pip", "install", str(wheel)], cwd=temporary_path)

        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        smoke_test = """
from pathlib import Path
import sys

import queryguard
from queryguard import StaticSqlCatalogProvider, SqlValidationService, load_catalog_from_yaml

venv_directory = Path(sys.argv[1]).resolve()
catalog_path = Path(sys.argv[2]).resolve()
if not Path(queryguard.__file__).resolve().is_relative_to(venv_directory):
    raise RuntimeError("queryguard was not imported from the clean virtual environment")

catalog = load_catalog_from_yaml(catalog_path)
validator = SqlValidationService(StaticSqlCatalogProvider(catalog))
result = validator.validate("SELECT id FROM orders WHERE account_id = @user_id LIMIT 1")
if not result.valid:
    raise RuntimeError(f"wheel smoke validation failed: {result.errors}")
print(f"QueryGuard {queryguard.__version__} wheel smoke test passed")
"""
        _run(
            [str(python), "-c", smoke_test, str(venv_directory), str(EXAMPLE_CATALOG)],
            cwd=temporary_path,
            env=environment,
        )


if __name__ == "__main__":
    main()
