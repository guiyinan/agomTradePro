"""Validate the governed Qlib runtime-entrypoint inventory.

This guard keeps the inventory explicit while still checking source coverage.
It verifies that every registered entrance still exists, that its symbol marker
is present, that every runtime-config read file is registered, and that
consumers marked ``blocked`` do not reintroduce retired default-path/settings
bypasses.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "governance" / "qlib_runtime_entrypoints.json"
FORBIDDEN_BLOCKED_MARKERS = (
    "~/.qlib/qlib_data/cn_data",
    "/models/qlib",
    "QLIB_SETTINGS",
    "SystemSettingsModel.get_runtime_qlib_config",
)
RUNTIME_READ_MARKER = "get_runtime_qlib_config"
SOURCE_ROOTS = (ROOT / "apps", ROOT / "core", ROOT / "scripts")
SOURCE_EXCLUDED_PARTS = {"tests", "migrations", "__pycache__"}


def _load_inventory() -> dict[str, Any]:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Qlib runtime entrypoint inventory must be a JSON object")
    return payload


def _source_files_with_marker(marker: str) -> set[str]:
    """Return production source files containing one runtime marker."""

    matches: set[str] = set()
    checker_path = Path(__file__).resolve()
    for source_root in SOURCE_ROOTS:
        if not source_root.exists():
            continue
        for path in source_root.rglob("*.py"):
            if path.resolve() == checker_path:
                continue
            if any(part in SOURCE_EXCLUDED_PARTS for part in path.parts):
                continue
            if marker not in path.read_text(encoding="utf-8"):
                continue
            matches.add(path.relative_to(ROOT).as_posix())
    return matches


def validate_inventory() -> list[str]:
    """Return stable validation errors for the governed entrypoint inventory."""

    payload = _load_inventory()
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["entries must be a non-empty list"]

    errors: list[str] = []
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
    else:
        covered_runtime_files = coverage.get("runtime_read_files")
        if not isinstance(covered_runtime_files, list) or not all(
            isinstance(item, str) and item.strip() for item in covered_runtime_files
        ):
            errors.append("coverage.runtime_read_files must be a non-empty string list")
        else:
            normalized_covered = {str(item).replace("\\", "/") for item in covered_runtime_files}
            discovered_runtime_files = _source_files_with_marker(RUNTIME_READ_MARKER)
            for file_name in sorted(discovered_runtime_files - normalized_covered):
                errors.append(f"runtime read file is not inventoried: {file_name}")
            for file_name in sorted(normalized_covered - discovered_runtime_files):
                errors.append(f"inventoried runtime read file is missing marker: {file_name}")
    seen_ids: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            errors.append(f"entry[{index}] must be an object")
            continue
        entry_id = str(raw_entry.get("id") or "")
        file_name = str(raw_entry.get("file") or "")
        symbol = str(raw_entry.get("symbol") or "")
        if not entry_id:
            errors.append(f"entry[{index}] missing id")
        elif entry_id in seen_ids:
            errors.append(f"duplicate entry id: {entry_id}")
        else:
            seen_ids.add(entry_id)
        if not file_name:
            errors.append(f"{entry_id or index}: missing file")
            continue
        path = ROOT / file_name
        if not path.is_file():
            errors.append(f"{entry_id}: file does not exist: {file_name}")
            continue
        source = path.read_text(encoding="utf-8")
        if not symbol:
            errors.append(f"{entry_id}: missing symbol")
        elif not all(token and token in source for token in symbol.split(".")):
            errors.append(f"{entry_id}: symbol marker not found: {symbol}")

        if raw_entry.get("legacy_status") == "blocked":
            for marker in FORBIDDEN_BLOCKED_MARKERS:
                if marker in source:
                    errors.append(
                        f"{entry_id}: blocked consumer contains forbidden marker {marker}"
                    )

    return errors


def main() -> int:
    """Run the inventory guard and print a compact report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    errors = validate_inventory()
    if args.format == "json":
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    elif errors:
        print("Qlib runtime entrypoint inventory: FAIL")
        for error in errors:
            print(f"- {error}")
    else:
        entry_count = len(_load_inventory().get("entries", ()))
        print(f"Qlib runtime entrypoint inventory: {entry_count} entries validated")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
