"""
Validate UAT route baseline against current Django URL configuration.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_FILE = PROJECT_ROOT / "tests" / "uat" / "route_baseline.json"
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")

    import django
    from django.urls import resolve, Resolver404

    django.setup()

    if not BASELINE_FILE.exists():
        print(f"[FAIL] Baseline file not found: {BASELINE_FILE}")
        return 1

    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    must_resolve_paths = baseline.get("must_resolve_paths", [])
    corrections = []
    corrections.extend((baseline.get("page_route_corrections") or {}).values())
    corrections.extend((baseline.get("api_route_corrections") or {}).values())

    failed = []

    # Validate all mapped "correct paths" (except null / API-only sentinel)
    for path in corrections:
        if not path:
            continue
        try:
            resolve(path)
        except Resolver404:
            failed.append(f"Mapped correct path does not resolve: {path}")

    # Validate must-resolve list
    for path in must_resolve_paths:
        try:
            resolve(path)
        except Resolver404:
            failed.append(f"Must-resolve path does not resolve: {path}")

    if failed:
        print("[FAIL] UAT route baseline validation failed:")
        for item in failed:
            print(f"  - {item}")
        return 1

    print(f"[OK] UAT route baseline validated ({len(must_resolve_paths)} must-resolve paths).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
