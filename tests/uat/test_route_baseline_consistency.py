import json
from pathlib import Path

from django.urls import resolve


def test_route_baseline_correct_paths_resolve():
    baseline_file = Path("tests/uat/route_baseline.json")
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))

    mapped_paths = []
    mapped_paths.extend((baseline.get("page_route_corrections") or {}).values())
    mapped_paths.extend((baseline.get("api_route_corrections") or {}).values())

    for path in mapped_paths:
        if not path:
            # API-only or intentionally unmapped route
            continue
        resolve(path)


def test_route_baseline_must_resolve_paths():
    baseline_file = Path("tests/uat/route_baseline.json")
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))

    for path in baseline.get("must_resolve_paths", []):
        resolve(path)
