#!/usr/bin/env python
"""Select incremental quality-check targets from git diff."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

LINT_PREFIXES = ("apps/", "core/", "shared/", "scripts/", "tests/", "sdk/")
TYPECHECK_PREFIXES = ("apps/", "core/", "shared/")


def normalize_path(path_text: str) -> str:
    """Normalize a repository-relative path to POSIX form."""

    return Path(path_text.strip()).as_posix().lstrip("./")


def get_changed_files(base: str, head: str) -> list[str]:
    """Return changed files between two refs, or an empty list on git failure."""

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []

    return [normalize_path(line) for line in result.stdout.splitlines() if line.strip()]


def _is_python_file(path: str) -> bool:
    return path.endswith(".py")


def _matches_prefix(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def select_lint_targets(changed_files: list[str]) -> list[str]:
    """Return changed Python files suitable for lint/format checks."""

    return sorted(
        path
        for path in changed_files
        if _is_python_file(path) and _matches_prefix(path, LINT_PREFIXES)
    )


def select_typecheck_targets(changed_files: list[str]) -> list[str]:
    """Return changed Python files suitable for incremental mypy."""

    return sorted(
        path
        for path in changed_files
        if _is_python_file(path)
        and _matches_prefix(path, TYPECHECK_PREFIXES)
        and "/migrations/" not in path
        and "/tests/" not in path
    )


def select_domain_coverage_targets(changed_files: list[str]) -> list[str]:
    """Return changed domain module paths suitable for pytest-cov flags."""

    targets: set[str] = set()
    for path in changed_files:
        if not _is_python_file(path):
            continue
        if not path.startswith("apps/") or "/domain/" not in path or "/tests/" in path:
            continue
        module_path = path[:-3].replace("/", ".")
        if module_path.endswith(".__init__"):
            module_path = module_path[: -len(".__init__")]
        targets.add(module_path)
    return sorted(targets)


def select_targets(changed_files: list[str], profile: str) -> list[str]:
    """Dispatch to the requested target profile."""

    selectors = {
        "lint": select_lint_targets,
        "typecheck": select_typecheck_targets,
        "domain-coverage": select_domain_coverage_targets,
    }
    return selectors[profile](changed_files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Select incremental quality-check targets.")
    parser.add_argument("--base", default="origin/main", help="Base git ref.")
    parser.add_argument("--head", default="HEAD", help="Head git ref.")
    parser.add_argument(
        "--profile",
        choices=("lint", "typecheck", "domain-coverage"),
        required=True,
        help="Target selection profile.",
    )
    parser.add_argument(
        "--output-format",
        choices=("space", "json", "newline"),
        default="space",
        help="Output format.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print selection details to stderr.",
    )
    args = parser.parse_args()

    changed_files = get_changed_files(args.base, args.head)
    targets = select_targets(changed_files, args.profile)

    if args.verbose:
        print(f"# changed files: {len(changed_files)}", file=sys.stderr)
        print(f"# profile: {args.profile}", file=sys.stderr)
        print(f"# selected targets: {len(targets)}", file=sys.stderr)

    if args.output_format == "json":
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "changed_files": changed_files,
                    "targets": targets,
                }
            )
        )
    elif args.output_format == "newline":
        print("\n".join(targets))
    else:
        print(" ".join(targets))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
