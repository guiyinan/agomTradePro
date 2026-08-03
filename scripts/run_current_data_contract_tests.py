"""Run every pytest nodeid registered by the current-data contract manifest."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    from .check_current_data_contracts import (
        DEFAULT_MANIFEST_PATH,
        validate_current_data_contracts,
    )
except ImportError:  # pragma: no cover - exercised by direct script execution
    from check_current_data_contracts import DEFAULT_MANIFEST_PATH, validate_current_data_contracts

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _owning_test_class(path: Path, function_name: str) -> str | None:
    """Return the pytest class containing a test method, if any."""

    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def _walk_class(node: ast.ClassDef, prefix: str = "") -> str | None:
        qualified = f"{prefix}.{node.name}" if prefix else node.name
        for child in node.body:
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == function_name
            ):
                return qualified
            if isinstance(child, ast.ClassDef):
                found = _walk_class(child, qualified)
                if found:
                    return found
        return None

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            found = _walk_class(node)
            if found:
                return found
    return None


def _registered_nodeids(manifest_path: Path) -> list[str]:
    """Return stable, de-duplicated pytest nodeids from a validated manifest."""

    payload: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    contracts = payload.get("contracts", []) if isinstance(payload, Mapping) else []
    nodeids: list[str] = []
    seen: set[str] = set()
    for contract in contracts:
        if not isinstance(contract, Mapping):
            continue
        tests = contract.get("required_tests", [])
        if not isinstance(tests, Sequence) or isinstance(tests, str):
            continue
        for test in tests:
            if not isinstance(test, Mapping):
                continue
            test_file = str(test.get("test_file") or "").strip()
            test_function = str(test.get("test_function") or "").strip()
            class_name = _owning_test_class(PROJECT_ROOT / test_file, test_function)
            nodeid = (
                f"{test_file}::{class_name}::{test_function}"
                if class_name
                else f"{test_file}::{test_function}"
            )
            if test_file and test_function and nodeid not in seen:
                seen.add(nodeid)
                nodeids.append(nodeid)
    return nodeids


def run_registered_tests(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    pytest_args: Sequence[str] = (),
) -> int:
    """Validate the manifest, then execute all registered pytest nodeids."""

    violations = validate_current_data_contracts(manifest_path)
    if violations:
        for violation in violations:
            location = violation.path
            if violation.line is not None:
                location = f"{location}:{violation.line}"
            prefix = f"{location}: " if location else ""
            print(f"{prefix}{violation.code}: {violation.message}")
        print(f"Refusing to run current-data tests: {len(violations)} manifest violation(s)")
        return 1

    nodeids = _registered_nodeids(manifest_path)
    if not nodeids:
        print("Refusing to run current-data tests: manifest contains no pytest nodeids")
        return 1

    command = [sys.executable, "-m", "pytest", *pytest_args, *nodeids]
    print(f"Running {len(nodeids)} current-data contract nodeid(s)")
    print(" ".join(command))
    return subprocess.call(command, cwd=PROJECT_ROOT)


def main() -> int:
    """Parse CLI arguments and run registered tests."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument(
        "--pytest-arg",
        action="append",
        default=[],
        help="Argument passed to pytest; repeat for multiple arguments.",
    )
    args = parser.parse_args()
    return run_registered_tests(args.manifest, pytest_args=args.pytest_arg)


if __name__ == "__main__":
    raise SystemExit(main())
