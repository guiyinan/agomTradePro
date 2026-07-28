"""Build the bounded Web-to-TUI telemetry catalog from the reviewed matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_OUTPUT = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"


class ClassicRouteRecord(TypedDict):
    """One approved Classic route and its comparable TUI task."""

    url_name: str
    task_key: str
    screen_key: str
    template_path: str


class TelemetryCatalog(TypedDict):
    """Serialized runtime telemetry catalog."""

    version: str
    source_matrix: str
    source_sha256: str
    classic_routes: list[ClassicRouteRecord]
    tui_task_keys: list[str]


def _split_values(raw_value: str) -> list[str]:
    """Split one semicolon-delimited matrix field into non-empty values."""

    return [value.strip() for value in raw_value.split(";") if value.strip()]


def _primary_task_key(row: dict[str, str]) -> str:
    """Resolve the stable TUI task used to compare one Classic route."""

    redirect_target = str(row.get("redirect_target") or "").strip()
    if redirect_target:
        action_values = parse_qs(urlparse(redirect_target).query).get("action") or []
        if action_values:
            action_key = action_values[0].strip()
            if action_key and "{" not in action_key:
                return action_key

    action_keys = _split_values(str(row.get("target_action_keys") or ""))
    if action_keys:
        return action_keys[0]

    screen_key = str(row.get("target_screen_key") or "").strip()
    if not screen_key:
        raise ValueError(f"Migrated route lacks a TUI task: {row.get('template_path')}")
    return f"screen:{screen_key}"


def build_catalog(matrix_path: Path) -> TelemetryCatalog:
    """Build a deterministic, low-cardinality telemetry catalog."""

    matrix_bytes = matrix_path.read_bytes()
    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    classic_routes: list[ClassicRouteRecord] = []
    task_keys: set[str] = set()
    route_task_by_name: dict[str, str] = {}

    for row in rows:
        if (
            row.get("template_role") != "route_page"
            or row.get("destination_class") not in {"A", "B"}
            or row.get("status") not in {"migrated", "deleted"}
        ):
            continue

        task_key = _primary_task_key(row)
        screen_key = str(row.get("target_screen_key") or "").strip()
        template_path = str(row.get("template_path") or "").strip()
        task_keys.add(task_key)
        task_keys.add(f"screen:{screen_key}")
        task_keys.update(_split_values(str(row.get("target_action_keys") or "")))

        for url_name in _split_values(str(row.get("url_name") or "")):
            previous_task = route_task_by_name.get(url_name)
            if previous_task is not None and previous_task != task_key:
                raise ValueError(
                    f"Classic URL name maps to multiple tasks: "
                    f"{url_name} -> {previous_task}, {task_key}"
                )
            route_task_by_name[url_name] = task_key
            classic_routes.append(
                {
                    "url_name": url_name,
                    "task_key": task_key,
                    "screen_key": screen_key,
                    "template_path": template_path,
                }
            )

    classic_routes.sort(key=lambda item: (item["url_name"], item["template_path"]))
    return {
        "version": "web-to-tui-telemetry.v1",
        "source_matrix": matrix_path.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
        "classic_routes": classic_routes,
        "tui_task_keys": sorted(task_keys),
    }


def write_catalog(catalog: TelemetryCatalog, output_path: Path) -> None:
    """Write one deterministic telemetry catalog."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def check_catalog(catalog: TelemetryCatalog, output_path: Path) -> None:
    """Fail when the checked-in catalog differs from the reviewed matrix."""

    expected = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    if not output_path.exists() or output_path.read_text(encoding="utf-8") != expected:
        raise SystemExit(
            "Web-to-TUI telemetry catalog is stale; run "
            "python scripts/build_web_to_tui_telemetry_catalog.py --write"
        )


def main() -> None:
    """Run the catalog writer or consistency check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()

    catalog = build_catalog(args.matrix.resolve())
    if args.write:
        write_catalog(catalog, args.output.resolve())
    else:
        check_catalog(catalog, args.output.resolve())


if __name__ == "__main__":
    main()
