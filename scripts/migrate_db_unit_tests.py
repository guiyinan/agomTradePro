#!/usr/bin/env python
"""Move database-dependent Unit files into the central Component test tier."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "governance" / "test_tier_inventory.json"
DEFAULT_MAPPING = REPO_ROOT / "governance" / "test_id_migrations_2026-07-24.json"
PRESERVED_PATHS = frozenset(
    {
        # AGENTS.md fixes these paths as part of the high-risk TUI regression package.
        "tests/unit/test_internal_ssl_redirect.py",
        "tests/unit/test_tui_workbench.py",
    }
)


def build_moves(inventory_path: Path) -> list[tuple[str, str]]:
    """Build deterministic old-to-new paths from the current inventory."""
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    moves: list[tuple[str, str]] = []
    for item in payload["files"]:
        source = str(item["path"])
        if (
            source.startswith("tests/unit/")
            and bool(item["database_dependent"])
            and source not in PRESERVED_PATHS
        ):
            destination = source.replace("tests/unit/", "tests/component/", 1)
            moves.append((source, destination))
    return sorted(moves)


def validate_moves(moves: Sequence[tuple[str, str]]) -> list[str]:
    """Return safety violations before changing the filesystem."""
    violations: list[str] = []
    for source, destination in moves:
        source_path = (REPO_ROOT / source).resolve()
        destination_path = (REPO_ROOT / destination).resolve()
        if REPO_ROOT not in source_path.parents or REPO_ROOT not in destination_path.parents:
            violations.append(f"path escapes repository: {source} -> {destination}")
        if not source_path.is_file():
            violations.append(f"source is missing: {source}")
        if destination_path.exists():
            violations.append(f"destination already exists: {destination}")
    return violations


def apply_moves(moves: Sequence[tuple[str, str]], mapping_path: Path) -> None:
    """Apply validated moves without overwriting any destination."""
    for source, destination in moves:
        source_path = REPO_ROOT / source
        destination_path = REPO_ROOT / destination
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(destination_path)
    existing_mappings: list[dict[str, str]] = []
    if mapping_path.is_file():
        existing_payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        existing_mappings = [
            {
                "old_path": str(item["old_path"]),
                "new_path": str(item["new_path"]),
            }
            for item in existing_payload.get("mappings", [])
        ]
    merged = {(item["old_path"], item["new_path"]) for item in existing_mappings} | set(moves)
    mapping_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reason": "Database/HTTP boundary tests moved from Unit to Component tier",
                "mappings": [
                    {"old_path": source, "new_path": destination}
                    for source, destination in sorted(merged)
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Preview or apply the database-test migration."""
    args = parse_args(argv)
    moves = build_moves(args.inventory)
    violations = validate_moves(moves)
    for source, destination in moves:
        print(f"{source} -> {destination}")
    for violation in violations:
        print(f"ERROR: {violation}")
    if violations:
        return 1
    print(f"Validated {len(moves)} moves")
    if args.apply:
        apply_moves(moves, args.mapping)
        print(f"Wrote mapping: {args.mapping}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
