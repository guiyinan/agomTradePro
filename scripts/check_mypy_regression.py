#!/usr/bin/env python3
"""Run mypy while preventing growth of explicitly baselined legacy errors."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ERROR_PATTERN = re.compile(r"^(?P<path>.+?\.py):\d+(?::\d+)?: error: .*? \[(?P<code>[^\]]+)\]$")


def parse_error_counts(output: str) -> dict[str, Counter[str]]:
    """Group mypy errors by repository-relative path and error code."""

    counts: dict[str, Counter[str]] = {}
    for line in output.splitlines():
        match = ERROR_PATTERN.match(line.strip())
        if match is None:
            continue
        path = Path(match.group("path")).as_posix()
        counts.setdefault(path, Counter())[match.group("code")] += 1
    return counts


def find_regressions(
    observed: dict[str, Counter[str]], baseline: dict[str, dict[str, int]]
) -> list[str]:
    """Return error-count increases relative to the governed baseline."""

    regressions: list[str] = []
    for path, codes in sorted(observed.items()):
        allowed_codes = baseline.get(path, {})
        for code, count in sorted(codes.items()):
            allowed = int(allowed_codes.get(code, 0))
            if count > allowed:
                regressions.append(f"{path}: {code} increased from {allowed} to {count}")
    return regressions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        default="governance/mypy_error_baseline.json",
        help="Governed legacy mypy error baseline.",
    )
    parser.add_argument("targets", nargs="+", help="Python files to check.")
    args = parser.parse_args()

    baseline_payload = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    baseline = baseline_payload.get("modules", {})
    command = [
        sys.executable,
        "-m",
        "mypy",
        "--config-file",
        "pyproject.toml",
        "--follow-imports=silent",
        *args.targets,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if combined_output:
        print(combined_output, end="" if combined_output.endswith("\n") else "\n")

    observed = parse_error_counts(combined_output)
    regressions = find_regressions(observed, baseline)
    if regressions:
        print("Mypy regression(s):", file=sys.stderr)
        for regression in regressions:
            print(f"- {regression}", file=sys.stderr)
        return 1

    legacy_count = sum(sum(codes.values()) for codes in observed.values())
    print(f"Mypy regressions: 0 (legacy errors observed: {legacy_count})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
