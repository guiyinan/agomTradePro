"""Guard Data Center provider credentials against new ORM bypasses."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "governance" / "data_center_provider_credential_contracts.json"


def _load_contract() -> dict[str, Any]:
    with CONTRACT_PATH.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise SystemExit("provider credential contract must be an object")
    return raw


def _production_files() -> list[Path]:
    paths: list[Path] = []
    for source_root in (ROOT / "apps", ROOT / "core", ROOT / "shared"):
        paths.extend(source_root.rglob("*.py"))
    return sorted(paths)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _allowed(path: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, path) for pattern in patterns)


def _entrypoint_exists(entrypoints: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for entry in entrypoints:
        path = ROOT / str(entry.get("path") or "")
        symbol = str(entry.get("symbol") or "")
        if not path.is_file():
            errors.append(f"missing entrypoint file: {path}")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            errors.append(f"cannot parse {path}: {type(exc).__name__}")
            continue
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        if symbol not in names:
            errors.append(f"missing entrypoint symbol: {entry['path']}::{symbol}")
    return errors


def _scan_file(path: Path, patterns: list[str]) -> list[str]:
    relative = _relative(path)
    if _allowed(relative, patterns):
        return []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
    except (OSError, SyntaxError) as exc:
        return [f"{relative}: parse error {type(exc).__name__}"]

    imported_provider_model = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in {"apps.data_center.models", "apps.data_center.infrastructure.models"}:
            continue
        if any(alias.name in {"ProviderConfigModel", "*"} for alias in node.names):
            imported_provider_model = True
            break
    direct_orm = bool(re.search(r"ProviderConfigModel\.(?:objects|_default_manager)", source))
    if imported_provider_model or direct_orm:
        return [
            f"{relative}: provider credential ORM bypass; use Data Center repository/public port"
        ]
    return []


def main() -> int:
    """Validate inventory and reject unregistered production ORM access."""

    contract = _load_contract()
    entrypoints = contract.get("entrypoints")
    patterns = contract.get("legacy_plaintext_paths")
    if not isinstance(entrypoints, list) or not isinstance(patterns, list):
        raise SystemExit(
            "provider credential contract requires entrypoints and legacy_plaintext_paths"
        )

    violations = _entrypoint_exists(
        [dict(entry) for entry in entrypoints if isinstance(entry, dict)]
    )
    allowed_patterns = [str(pattern) for pattern in patterns]
    for path in _production_files():
        violations.extend(_scan_file(path, allowed_patterns))
    if violations:
        print(json.dumps(violations, ensure_ascii=False, indent=2))
        return 1
    print(f"Data Center provider credential inventory: {len(entrypoints)} entries validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
