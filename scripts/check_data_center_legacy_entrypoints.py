"""Keep direct Data Center script imports and compatibility wrappers exact."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

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
WRAPPER_MARKER = "LEGACY_DATA_CENTER_WRAPPER"
DIRECT_STATUSES = {"blocked_retirement", "compatibility_owner"}
WRAPPER_STATUSES = {"compatibility_wrapper"}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _script_imports(path: Path) -> list[str]:
    tree = _parse(path)
    imports: list[str] = []
    for node in ast.walk(tree):
        module = node.module if isinstance(node, ast.ImportFrom) else None
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif module:
            imports.append(module)
    return [name for name in imports if name.startswith(INTERNAL_PREFIXES)]


def _wrapper_command(path: Path) -> str | None:
    """Return a declared canonical command from one compatibility wrapper."""

    for node in _parse(path).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == WRAPPER_MARKER for target in targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value.strip() or None
    return None


def _entry_map(raw: object, group: str, violations: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, list):
        violations.append(f"manifest_{group}_invalid")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            violations.append(f"{group}_item_invalid:{index}")
            continue
        path_text = str(item.get("path") or "").strip().replace("\\", "/")
        if not path_text:
            violations.append(f"{group}_path_missing:{index}")
        elif path_text in result:
            violations.append(f"{group}_path_duplicate:{path_text}")
        else:
            result[path_text] = item
    return result


def validate(
    *,
    manifest_path: Path = MANIFEST,
    scripts_root: Path | None = None,
    repository_root: Path = ROOT,
) -> list[str]:
    """Return exact-inventory, lifecycle, and wrapper routing violations."""

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    if str(payload.get("owner") or "") != "data_center":
        violations.append("manifest_owner_invalid")
    direct_entries = _entry_map(payload.get("entrypoints"), "entrypoints", violations)
    wrapper_entries = _entry_map(payload.get("wrappers"), "wrappers", violations)
    overlap = sorted(set(direct_entries) & set(wrapper_entries))
    violations.extend(f"entrypoint_wrapper_overlap:{path}" for path in overlap)

    resolved_scripts_root = scripts_root or repository_root / "scripts"
    discovered_direct: dict[str, list[str]] = {}
    discovered_wrappers: dict[str, str] = {}
    for path in sorted(resolved_scripts_root.rglob("*.py")):
        path_text = path.relative_to(repository_root).as_posix()
        if path_text in EXCLUDED_PATHS:
            continue
        imports = _script_imports(path)
        if imports:
            discovered_direct[path_text] = imports
        wrapper_command = _wrapper_command(path)
        if wrapper_command:
            discovered_wrappers[path_text] = wrapper_command

    for path_text in sorted(set(discovered_direct) - set(direct_entries)):
        violations.append(f"unregistered_script_entrypoint:{path_text}")
    for path_text in sorted(set(direct_entries) - set(discovered_direct)):
        violations.append(f"stale_script_entrypoint:{path_text}")
    for path_text in sorted(set(discovered_wrappers) - set(wrapper_entries)):
        violations.append(f"unregistered_compatibility_wrapper:{path_text}")
    for path_text in sorted(set(wrapper_entries) - set(discovered_wrappers)):
        violations.append(f"stale_compatibility_wrapper:{path_text}")

    for path_text, item in sorted(direct_entries.items()):
        status = str(item.get("status") or "")
        if status not in DIRECT_STATUSES:
            violations.append(f"direct_status_invalid:{path_text}:{status}")
        if not str(item.get("replacement") or "").strip():
            violations.append(f"replacement_missing:{path_text}")

    for path_text, item in sorted(wrapper_entries.items()):
        status = str(item.get("status") or "")
        if status not in WRAPPER_STATUSES:
            violations.append(f"wrapper_status_invalid:{path_text}:{status}")
        replacement = str(item.get("replacement") or "").strip()
        if not replacement:
            violations.append(f"replacement_missing:{path_text}")
        command = discovered_wrappers.get(path_text)
        if command and command not in replacement.split():
            violations.append(f"wrapper_replacement_mismatch:{path_text}:{command}")
        if path_text in discovered_direct:
            violations.append(f"wrapper_imports_data_center_internal:{path_text}")
    return sorted(set(violations))


def main() -> int:
    """Fail closed when the direct and wrapper inventories are not exact."""

    try:
        violations = validate()
    except (OSError, SyntaxError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"legacy script entrypoint guard failed: {exc}") from exc
    if violations:
        raise SystemExit(
            "Data Center legacy script entrypoint violations: " + "; ".join(violations)
        )
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    direct = payload.get("entrypoints")
    wrappers = payload.get("wrappers")
    direct_count = len(direct) if isinstance(direct, list) else 0
    wrapper_count = len(wrappers) if isinstance(wrappers, list) else 0
    print(
        "Data Center legacy script entrypoints: "
        f"{direct_count} direct, {wrapper_count} compatibility wrappers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
