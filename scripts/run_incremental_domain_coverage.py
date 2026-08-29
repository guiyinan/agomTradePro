#!/usr/bin/env python
"""Run per-app Domain line coverage against shared and app-owned unit tests.

The repository-wide Nightly ratchet separately enforces each app's historical
branch floor.  This fast gate intentionally uses a source-free coverage config
so imports from neighbouring apps cannot dilute or inflate the changed app.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCREMENTAL_COVERAGE_CONFIG = "config/coverage/incremental-domain.coveragerc"


def _imports_domain_module(test_path: Path, domain_module: str) -> bool:
    """Return whether one test directly imports the selected Domain package."""

    source = test_path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(
                alias.name == domain_module or alias.name.startswith(f"{domain_module}.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module == domain_module or node.module.startswith(f"{domain_module}."):
                return True
    return False


def _direct_domain_test_targets(
    domain_module: str,
    *,
    selected_directories: list[Path],
    root: Path,
) -> list[str]:
    """Find unit tests outside app-owned directories that import the Domain."""

    unit_root = root / "tests" / "unit"
    if not unit_root.is_dir():
        return []
    targets: list[str] = []
    for test_path in sorted(unit_root.rglob("test_*.py")):
        if any(test_path.is_relative_to(directory) for directory in selected_directories):
            continue
        if _imports_domain_module(test_path, domain_module):
            targets.append(test_path.relative_to(root).as_posix())
    return targets


def select_domain_test_targets(
    modules: list[str],
    *,
    root: Path = ROOT,
) -> list[str]:
    """Return existing shared and app-owned test directories for Domain modules."""

    candidates = ["tests/unit/domain"]
    app_names = {
        parts[1]
        for module in modules
        if len(parts := module.split(".")) >= 3 and parts[0] == "apps" and parts[2] == "domain"
    }
    for app_name in sorted(app_names):
        candidates.extend((f"tests/unit/{app_name}", f"apps/{app_name}/tests"))
    selected = [candidate for candidate in candidates if (root / candidate).is_dir()]
    selected_directories = [root / candidate for candidate in selected]
    for app_name in sorted(app_names):
        selected.extend(
            _direct_domain_test_targets(
                f"apps.{app_name}.domain",
                selected_directories=selected_directories,
                root=root,
            )
        )
    return selected


def build_pytest_command(
    module: str,
    *,
    fail_under: int,
    root: Path = ROOT,
) -> list[str]:
    """Build one deterministic pytest-cov command for an app Domain package."""

    test_targets = select_domain_test_targets([module], root=root)
    if not test_targets:
        raise ValueError("no Domain test targets are available")
    command = [
        sys.executable,
        "-m",
        "pytest",
        *test_targets,
        "-v",
        "--tb=short",
        "-o",
        "addopts=",
        f"--cov-config={INCREMENTAL_COVERAGE_CONFIG}",
        f"--cov-fail-under={fail_under}",
        "--cov-report=term-missing",
    ]
    command.append(f"--cov={module}")
    return command


def build_pytest_commands(
    modules: list[str],
    *,
    fail_under: int,
    root: Path = ROOT,
) -> list[list[str]]:
    """Build isolated commands so one well-tested app cannot hide another app."""

    return [
        build_pytest_command(module, fail_under=fail_under, root=root)
        for module in sorted(set(modules))
    ]


def main() -> int:
    """Parse changed modules and run the incremental Domain coverage gate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="+", help="Changed Domain module import paths.")
    parser.add_argument("--fail-under", type=int, default=90)
    args = parser.parse_args()

    for command in build_pytest_commands(args.modules, fail_under=args.fail_under):
        print("Running incremental Domain coverage gate:", flush=True)
        print(" ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
