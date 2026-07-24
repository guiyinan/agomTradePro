#!/usr/bin/env python
"""Run the machine-selected no-database TDD suite with a hard time budget."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "governance" / "test_tier_inventory.json"
DEFAULT_BASELINE = REPO_ROOT / "governance" / "testing_quality_baseline.json"


def load_fast_files(path: Path) -> list[str]:
    """Load the stable fast-suite file list."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("fast_files", [])
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise ValueError(f"Invalid fast_files in {path}")
    if not files:
        raise ValueError(f"Fast suite is empty in {path}")
    return files


def load_budget(path: Path) -> float:
    """Load the fast-suite runtime budget in seconds."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return float(payload["fast_suite"]["maximum_seconds"])


def build_pytest_command(files: Sequence[str], extra_args: Sequence[str]) -> list[str]:
    """Build the isolated pytest invocation."""
    return [
        sys.executable,
        "-m",
        "pytest",
        *files,
        "-q",
        "--strict-markers",
        "--durations=20",
        "-p",
        "tests.support.fast_suite_guard",
        *extra_args,
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--list", action="store_true", help="print selected files only")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fast suite and enforce its runtime budget."""
    args = parse_args(argv)
    files = load_fast_files(args.inventory)
    if args.list:
        print("\n".join(files))
        return 0

    extra_args = list(args.pytest_args)
    if extra_args[:1] == ["--"]:
        extra_args = extra_args[1:]
    command = build_pytest_command(files, extra_args)
    started = time.perf_counter()
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    elapsed = time.perf_counter() - started
    budget = load_budget(args.baseline)
    print(f"Fast suite elapsed: {elapsed:.2f}s (budget: {budget:.0f}s)")
    if result.returncode != 0:
        return result.returncode
    if elapsed > budget:
        print(f"ERROR: fast suite exceeded the {budget:.0f}s budget")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
