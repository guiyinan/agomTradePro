#!/usr/bin/env python3
"""Keep full-production mypy debt exact and monotonically decreasing."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = Path("governance/mypy_debt_baseline.json")
DEFAULT_TARGETS = ("apps", "core", "shared")
PRODUCTION_EXCLUDE = r"(^|[\\/])(tests|migrations)([\\/]|$)"
ERROR_PATTERN = re.compile(r"^(?P<path>.+?\.py):\d+(?::\d+)?: error: .*? \[(?P<code>[^\]]+)\]$")

ErrorCounts = dict[str, Counter[str]]
SerializedErrorCounts = dict[str, dict[str, int]]


def parse_error_counts(output: str) -> ErrorCounts:
    """Parse mypy output into repository-relative per-file, per-code counts."""

    counts: ErrorCounts = {}
    for line in output.splitlines():
        match = ERROR_PATTERN.match(line.strip())
        if match is None:
            continue
        path = match.group("path").replace("\\", "/")
        counts.setdefault(path, Counter())[match.group("code")] += 1
    return counts


def serialize_counts(counts: ErrorCounts) -> SerializedErrorCounts:
    """Return stable JSON-ready counts."""

    return {
        path: dict(sorted(code_counts.items()))
        for path, code_counts in sorted(counts.items())
        if code_counts
    }


def summarize_counts(counts: SerializedErrorCounts) -> dict[str, int]:
    """Return aggregate error and affected-file totals."""

    return {
        "errors": sum(sum(code_counts.values()) for code_counts in counts.values()),
        "files_with_errors": len(counts),
    }


def find_count_changes(
    candidate: SerializedErrorCounts,
    ceiling: SerializedErrorCounts,
) -> tuple[list[str], list[str]]:
    """Return candidate increases and decreases relative to a ceiling."""

    increases: list[str] = []
    decreases: list[str] = []
    paths = sorted(set(candidate) | set(ceiling))
    for path in paths:
        candidate_codes = candidate.get(path, {})
        ceiling_codes = ceiling.get(path, {})
        for code in sorted(set(candidate_codes) | set(ceiling_codes)):
            current = int(candidate_codes.get(code, 0))
            allowed = int(ceiling_codes.get(code, 0))
            if current > allowed:
                increases.append(f"{path}: {code} increased from {allowed} to {current}")
            elif current < allowed:
                decreases.append(f"{path}: {code} decreased from {allowed} to {current}")
    return increases, decreases


def find_increased_error_lines(
    output: str,
    candidate: SerializedErrorCounts,
    ceiling: SerializedErrorCounts,
) -> list[str]:
    """Return exact mypy diagnostics for file/code pairs above the ceiling."""

    increased_keys = {
        (path, code)
        for path, code_counts in candidate.items()
        for code, current in code_counts.items()
        if current > int(ceiling.get(path, {}).get(code, 0))
    }
    diagnostics: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = ERROR_PATTERN.match(line)
        if match is None:
            continue
        key = (match.group("path").replace("\\", "/"), match.group("code"))
        if key in increased_keys:
            diagnostics.append(line)
    return diagnostics


def build_payload(counts: ErrorCounts) -> dict[str, Any]:
    """Build the deterministic debt-baseline payload."""

    modules = serialize_counts(counts)
    return {
        "schema_version": 1,
        "scope": {
            "targets": list(DEFAULT_TARGETS),
            "exclude": PRODUCTION_EXCLUDE,
            "follow_imports": "skip",
        },
        "summary": summarize_counts(modules),
        "modules": modules,
    }


def load_payload(path: Path) -> dict[str, Any]:
    """Load one baseline payload."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Mypy debt baseline must be a JSON object: {path}")
    return cast(dict[str, Any], payload)


def load_reference_payload(reference_ref: str, baseline_path: Path) -> dict[str, Any] | None:
    """Load the baseline from a git ref, returning None during first-time bootstrap."""

    relative_path = baseline_path.resolve().relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        ["git", "show", f"{reference_ref}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError(f"Reference mypy debt baseline must be a JSON object: {reference_ref}")
    return cast(dict[str, Any], payload)


def validate_payload(payload: dict[str, Any]) -> list[str]:
    """Validate baseline metadata and aggregate consistency."""

    problems: list[str] = []
    expected_scope = {
        "targets": list(DEFAULT_TARGETS),
        "exclude": PRODUCTION_EXCLUDE,
        "follow_imports": "skip",
    }
    if payload.get("schema_version") != 1:
        problems.append("schema_version must be 1")
    if payload.get("scope") != expected_scope:
        problems.append("scope does not match the governed production mypy command")
    modules = payload.get("modules")
    if not isinstance(modules, dict):
        problems.append("modules must be an object")
        return problems
    if payload.get("summary") != summarize_counts(modules):
        problems.append("summary does not match per-file, per-code module counts")
    return problems


def run_mypy() -> tuple[int, str, ErrorCounts]:
    """Run the governed full-production mypy command."""

    command = [
        sys.executable,
        "-m",
        "mypy",
        "--config-file",
        "pyproject.toml",
        "--follow-imports=skip",
        "--exclude",
        PRODUCTION_EXCLUDE,
        *DEFAULT_TARGETS,
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return result.returncode, output, parse_error_counts(output)


def _print_items(title: str, items: list[str]) -> None:
    """Print a compact diagnostics section."""

    if not items:
        return
    print(title, file=sys.stderr)
    for item in items[:50]:
        print(f"- {item}", file=sys.stderr)
    if len(items) > 50:
        print(f"- ... and {len(items) - 50} more", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--reference-ref",
        help="Git ref whose baseline is the maximum allowed debt ceiling.",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Rewrite the baseline after verified debt reduction.",
    )
    args = parser.parse_args()
    baseline_path = (REPO_ROOT / args.baseline).resolve()

    returncode, output, observed = run_mypy()
    if returncode not in (0, 1):
        if output:
            print(output, file=sys.stderr)
        print(f"mypy failed unexpectedly with exit code {returncode}", file=sys.stderr)
        return 2

    candidate = build_payload(observed)
    reference = (
        load_reference_payload(args.reference_ref, baseline_path) if args.reference_ref else None
    )
    if reference is not None:
        reference_problems = validate_payload(reference)
        if reference_problems:
            _print_items("Reference baseline is invalid:", reference_problems)
            return 2
        increases, _ = find_count_changes(candidate["modules"], reference["modules"])
        if increases:
            _print_items("Full mypy debt increased relative to the base ref:", increases)
            _print_items(
                "Exact increased mypy diagnostics:",
                find_increased_error_lines(output, candidate["modules"], reference["modules"]),
            )
            return 1

    if args.write_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary = candidate["summary"]
        print(
            f"Wrote mypy debt baseline: {summary['errors']} errors in "
            f"{summary['files_with_errors']} files"
        )
        return 0

    if not baseline_path.is_file():
        print(f"Missing mypy debt baseline: {baseline_path}", file=sys.stderr)
        return 2

    baseline = load_payload(baseline_path)
    problems = validate_payload(baseline)
    if problems:
        _print_items("Mypy debt baseline is invalid:", problems)
        return 2

    increases, decreases = find_count_changes(candidate["modules"], baseline["modules"])
    if increases:
        _print_items("Full mypy debt exceeded the checked-in ceiling:", increases)
        _print_items(
            "Exact increased mypy diagnostics:",
            find_increased_error_lines(output, candidate["modules"], baseline["modules"]),
        )
    if decreases:
        _print_items(
            "Full mypy debt decreased; refresh the checked-in baseline with " "--write-baseline:",
            decreases,
        )
    if increases or decreases:
        return 1

    summary = candidate["summary"]
    print(
        f"Full mypy debt ceiling passed: {summary['errors']} errors in "
        f"{summary['files_with_errors']} files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
