"""Ensure every legacy script Data Center import is explicitly inventoried."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance" / "data_center_legacy_entrypoints.json"
INTERNAL_PREFIXES = (
    "apps.data_center.infrastructure",
    "apps.data_center.application.interface_services",
    "apps.data_center.application.query_services",
    "apps.data_center.application.read_facade",
)
EXCLUDED_PATHS = {
    "scripts/check_data_center_legacy_entrypoints.py",
    "scripts/check_data_center_provider_credentials.py",
    "scripts/data_center_architecture_inventory.py",
}


def _script_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        module = node.module if isinstance(node, ast.ImportFrom) else None
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif module:
            imports.append(module)
    return [name for name in imports if name.startswith(INTERNAL_PREFIXES)]


def validate() -> list[str]:
    """Return direct-script-imports that lack a manifest entry."""

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = payload.get("entrypoints")
    if not isinstance(entries, list):
        return ["manifest_entrypoints_invalid"]
    entry_by_path = {
        str(item.get("path")): item
        for item in entries
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    violations: list[str] = []
    if str(payload.get("owner") or "") != "data_center":
        violations.append("manifest_owner_invalid")
    for path_text, item in sorted(entry_by_path.items()):
        path = ROOT / path_text
        if not path.exists():
            violations.append(f"entrypoint_missing:{path_text}")
            continue
        if not str(item.get("replacement") or "").strip():
            violations.append(f"replacement_missing:{path_text}")
        if not str(item.get("status") or "").strip():
            violations.append(f"status_missing:{path_text}")
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        path_text = path.relative_to(ROOT).as_posix()
        if path_text in EXCLUDED_PATHS:
            continue
        if _script_imports(path) and path_text not in entry_by_path:
            violations.append(f"unregistered_script_entrypoint:{path_text}")
    return sorted(violations)


def main() -> int:
    """Fail closed when a legacy script import is not registered."""

    try:
        violations = validate()
    except (OSError, SyntaxError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"legacy script entrypoint guard failed: {exc}") from exc
    if violations:
        raise SystemExit(
            "Data Center legacy script entrypoint violations: " + "; ".join(violations)
        )
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = payload.get("entrypoints")
    entry_count = len(entries) if isinstance(entries, list) else 0
    print(f"Data Center legacy script entrypoints: {entry_count} registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
