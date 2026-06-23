"""Validate AgomTradePro TUI metadata JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a TUI metadata JSON file.")
    parser.add_argument("path", help="Path to generated or published TUI metadata JSON")
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")

    import django

    django.setup()

    from apps.terminal.application.tui_metadata import validate_tui_metadata

    path = (root / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    validated = validate_tui_metadata(payload)
    canonical = json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(path),
                "hash": digest,
                "schema_version": validated.get("schema_version", ""),
                "groups": len(validated["groups"]),
                "modules": len(validated["modules"]),
                "screens": len(validated["screens"]),
                "actions": len(validated["actions"]),
                "default_screen": validated["default_screen"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
