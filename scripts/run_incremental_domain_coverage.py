#!/usr/bin/env python
"""Run changed Domain coverage against shared and app-owned unit tests."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    return [candidate for candidate in candidates if (root / candidate).is_dir()]


def build_pytest_command(
    modules: list[str],
    *,
    fail_under: int,
    root: Path = ROOT,
) -> list[str]:
    """Build the deterministic pytest-cov command for changed Domain modules."""

    test_targets = select_domain_test_targets(modules, root=root)
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
        f"--cov-fail-under={fail_under}",
        "--cov-report=term-missing",
    ]
    command.extend(f"--cov={module}" for module in modules)
    return command


def main() -> int:
    """Parse changed modules and run the incremental Domain coverage gate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="+", help="Changed Domain module import paths.")
    parser.add_argument("--fail-under", type=int, default=70)
    args = parser.parse_args()

    command = build_pytest_command(args.modules, fail_under=args.fail_under)
    print("Running incremental Domain coverage gate:", flush=True)
    print(" ".join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
