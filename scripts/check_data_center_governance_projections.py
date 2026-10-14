#!/usr/bin/env python3
"""Check every generated Data Center governance projection with one command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTION_CHECKS = (
    ("architecture inventory", "scripts/data_center_architecture_inventory.py"),
    ("entrypoint inventory", "scripts/data_center_entrypoint_inventory.py"),
    ("module map", "scripts/check_module_map.py"),
)


def _run_projection(script_path: str) -> int:
    """Run one projection checker in the repository interpreter and root."""

    completed = subprocess.run(
        [sys.executable, script_path],
        cwd=REPO_ROOT,
        check=False,
    )
    return completed.returncode


def check_data_center_governance_projections() -> tuple[str, ...]:
    """Return the names of every stale or invalid generated projection."""

    failures: list[str] = []
    for name, script_path in PROJECTION_CHECKS:
        if _run_projection(script_path) != 0:
            failures.append(name)
    return tuple(failures)


def main() -> int:
    """Run the unified local and CI projection gate."""

    failures = check_data_center_governance_projections()
    if failures:
        print(
            "Data Center governance projections failed: " + ", ".join(failures),
            file=sys.stderr,
        )
        return 1
    print("Data Center governance projections OK: architecture, entrypoints, module map")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
