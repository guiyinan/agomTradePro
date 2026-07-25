#!/usr/bin/env python
"""Reject changed production Python files that grow beyond the headroom limit."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GROWTH_LIMIT = 1000
PRODUCTION_PREFIXES = ("apps/", "core/", "shared/")


@dataclass(frozen=True)
class ChangedPythonFile:
    """One production Python path at the base and head revisions."""

    base_path: str | None
    head_path: str


@dataclass(frozen=True)
class FileSizeGrowth:
    """One changed file that exceeded the incremental growth guard."""

    path: str
    base_non_empty_lines: int
    head_non_empty_lines: int


def normalize_path(path_text: str) -> str:
    """Normalize a repository-relative path to POSIX form."""

    return Path(path_text.strip()).as_posix().lstrip("./")


def is_production_python_file(path: str) -> bool:
    """Return whether the path is governed production Python source."""

    normalized = normalize_path(path)
    return (
        normalized.endswith(".py")
        and normalized.startswith(PRODUCTION_PREFIXES)
        and "/migrations/" not in normalized
        and "/tests/" not in normalized
    )


def count_non_empty_lines(source: str) -> int:
    """Count non-empty physical lines in Python source."""

    return sum(1 for line in source.splitlines() if line.strip())


def parse_name_status(output: str) -> list[ChangedPythonFile]:
    """Parse ``git diff --name-status`` output into production Python changes."""

    changes: list[ChangedPythonFile] = []
    for raw_line in output.splitlines():
        columns = raw_line.split("\t")
        if len(columns) < 2:
            continue
        status = columns[0]
        if status.startswith(("R", "C")) and len(columns) >= 3:
            base_path = normalize_path(columns[1])
            head_path = normalize_path(columns[2])
        else:
            head_path = normalize_path(columns[1])
            base_path = None if status == "A" else head_path
        if is_production_python_file(head_path):
            changes.append(ChangedPythonFile(base_path=base_path, head_path=head_path))
    return changes


def get_changed_python_files(base: str, head: str) -> list[ChangedPythonFile]:
    """Return added or modified production Python files between two refs."""

    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "--find-renames",
            "--diff-filter=ACMRT",
            f"{base}...{head}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_name_status(result.stdout)


def read_revision_file(revision: str, path: str) -> str:
    """Read one repository file exactly as stored at a Git revision."""

    return subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def find_growth_violations(
    changes: list[ChangedPythonFile],
    *,
    base: str,
    head: str,
    growth_limit: int,
) -> list[FileSizeGrowth]:
    """Return files that grew while already beyond the headroom limit."""

    violations: list[FileSizeGrowth] = []
    for change in changes:
        head_count = count_non_empty_lines(read_revision_file(head, change.head_path))
        base_count = (
            count_non_empty_lines(read_revision_file(base, change.base_path))
            if change.base_path is not None
            else 0
        )
        if head_count > growth_limit and head_count > base_count:
            violations.append(
                FileSizeGrowth(
                    path=change.head_path,
                    base_non_empty_lines=base_count,
                    head_non_empty_lines=head_count,
                )
            )
    return violations


def main() -> int:
    """Run the incremental Python file-size guard."""

    parser = argparse.ArgumentParser(
        description=(
            "Reject production Python files that grow beyond the incremental " "headroom limit."
        )
    )
    parser.add_argument("--base", required=True, help="Base Git revision.")
    parser.add_argument("--head", required=True, help="Head Git revision.")
    parser.add_argument(
        "--growth-limit",
        type=int,
        default=DEFAULT_GROWTH_LIMIT,
        help="Maximum non-empty lines allowed for a growing file.",
    )
    args = parser.parse_args()
    if args.growth_limit <= 0:
        parser.error("--growth-limit must be positive")

    changes = get_changed_python_files(args.base, args.head)
    violations = find_growth_violations(
        changes,
        base=args.base,
        head=args.head,
        growth_limit=args.growth_limit,
    )
    if violations:
        print(
            "Changed production Python files exhausted their size headroom "
            f"(limit: {args.growth_limit} non-empty lines):"
        )
        for violation in violations:
            print(
                f"- {violation.path}: {violation.base_non_empty_lines} -> "
                f"{violation.head_non_empty_lines}"
            )
        print("Split responsibility before adding more code to these files.")
        return 1

    print(
        f"Python file-size growth guard passed for {len(changes)} changed "
        f"production files (limit: {args.growth_limit})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
