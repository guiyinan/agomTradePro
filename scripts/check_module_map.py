#!/usr/bin/env python
"""Verify that ``governance/module_map.json`` matches the current source tree.

The module map is a generated projection (see ``scripts/build_module_map.py``);
this script regenerates it in memory and fails when the committed file has
drifted from the code, printing a concise per-module/per-field diff summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_module_map import (  # noqa: E402
    DEFAULT_OUTPUT,
    GENERATED_BY,
    SCHEMA_VERSION,
    build_module_map,
)

REMEDIATION = "run: python scripts/build_module_map.py"


def _load_committed(path: Path) -> dict[str, object]:
    """Load the committed module map, exiting with a clear error when invalid."""

    if not path.exists():
        raise SystemExit(f"module map missing: {path}\n{REMEDIATION}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"module map is not valid JSON: {path}: {exc}\n{REMEDIATION}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"module map root must be a JSON object: {path}\n{REMEDIATION}")
    return payload


def _validate_envelope(payload: dict[str, object]) -> list[str]:
    """Validate schema identity fields of a module map payload."""

    problems: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version: expected {SCHEMA_VERSION!r}, got {payload.get('schema_version')!r}"
        )
    if payload.get("generated_by") != GENERATED_BY:
        problems.append(
            f"generated_by: expected {GENERATED_BY!r}, got {payload.get('generated_by')!r}"
        )
    return problems


def _diff_modules(
    committed: dict[str, object], regenerated: dict[str, object]
) -> list[str]:
    """Return a concise module/field-level diff summary between two payloads."""

    committed_modules = committed.get("modules", {})
    regenerated_modules = regenerated.get("modules", {})
    if not isinstance(committed_modules, dict) or not isinstance(regenerated_modules, dict):
        return ["modules: not a JSON object in one of the payloads"]

    lines: list[str] = []
    committed_names = set(committed_modules)
    regenerated_names = set(regenerated_modules)
    for name in sorted(committed_names - regenerated_names):
        lines.append(f"module removed from code, still in file: {name}")
    for name in sorted(regenerated_names - committed_names):
        lines.append(f"module added in code, missing in file: {name}")
    for name in sorted(committed_names & regenerated_names):
        committed_record = committed_modules[name]
        regenerated_record = regenerated_modules[name]
        if committed_record == regenerated_record:
            continue
        if not isinstance(committed_record, dict) or not isinstance(regenerated_record, dict):
            lines.append(f"{name}: record is not a JSON object")
            continue
        fields = sorted(set(committed_record) | set(regenerated_record))
        differing = [
            field
            for field in fields
            if committed_record.get(field) != regenerated_record.get(field)
        ]
        lines.append(f"{name}: fields differ: {', '.join(differing)}")
    return lines


def main() -> int:
    """Regenerate the module map in memory and compare it with the committed file."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="committed module map JSON path to verify",
    )
    args = parser.parse_args()

    committed = _load_committed(args.file)
    envelope_problems = _validate_envelope(committed)
    if envelope_problems:
        for problem in envelope_problems:
            print(f"INVALID {problem}")
        print(f"module map drift detected: {args.file}\n{REMEDIATION}")
        return 1

    regenerated = build_module_map()
    if committed == regenerated:
        modules = regenerated["modules"]
        module_count = len(modules) if isinstance(modules, dict) else 0
        edge_count = sum(
            len(record.get("depends_on", {}))
            for record in (modules.values() if isinstance(modules, dict) else [])
            if isinstance(record, dict) and isinstance(record.get("depends_on"), dict)
        )
        print(f"module map OK: {args.file} matches the source tree "
              f"(modules={module_count} edges={edge_count})")
        return 0

    print(f"module map drift detected: {args.file}")
    for line in _diff_modules(committed, regenerated):
        print(f"- {line}")
    print(REMEDIATION)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
