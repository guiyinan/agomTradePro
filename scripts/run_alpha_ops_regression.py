"""Run the focused regression suite for async task visibility and Alpha provider alerts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_TARGETS = [
    "apps/alpha/tests/test_ops_use_cases.py",
    "apps/alpha/tests/test_services_metadata.py",
    "apps/alpha/tests/test_services_provider_alerts.py",
    "apps/alpha/tests/test_ops_interface_contracts.py",
    "apps/dashboard/tests/test_alpha_queries.py",
    "apps/dashboard/tests/test_alpha_views.py",
    "tests/api/test_policy_api_edges.py",
    "tests/unit/data_center/test_interface_services.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the focused async task visibility and Alpha alert regression suite.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Run pytest with verbose output.",
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Extra pytest arguments appended after the default target list.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    command = [sys.executable, "-m", "pytest"]
    if args.verbose:
        command.append("-v")
    else:
        command.append("-q")
    command.extend(DEFAULT_TARGETS)
    command.extend(args.pytest_args)

    print("Running Alpha ops regression suite:")
    for target in DEFAULT_TARGETS:
        print(f"  - {target}")
    if args.pytest_args:
        print("Extra pytest args:")
        for item in args.pytest_args:
            print(f"  - {item}")

    completed = subprocess.run(command, cwd=repo_root)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
