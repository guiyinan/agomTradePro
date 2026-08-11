"""Guard Data Center provider credentials against new ORM bypasses."""

from __future__ import annotations

import ast
import json
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
        paths.extend(
            path
            for path in source_root.rglob("*.py")
            if "migrations" not in path.parts and "tests" not in path.parts
        )
    return sorted(paths)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


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


def _scan_file(path: Path) -> list[str]:
    relative = _relative(path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
    except (OSError, SyntaxError) as exc:
        return [f"{relative}: parse error {type(exc).__name__}"]

    violations: list[str] = []
    forbidden_tokens = {
        "ProviderCredentialModel",
        "allow_legacy_fallback",
        "migrate_legacy",
        "provider_credential_models",
    }
    for token in sorted(forbidden_tokens):
        if token in source:
            violations.append(f"{relative}: legacy provider credential token: {token}")
    if relative == "apps/data_center/infrastructure/models.py":
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != "ProviderConfigModel":
                continue
            for statement in node.body:
                if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in {"api_key", "api_secret"}:
                            violations.append(
                                f"{relative}:{statement.lineno}: plaintext provider field: {target.id}"
                            )
    return violations


def main() -> int:
    """Validate inventory and reject unregistered production ORM access."""

    contract = _load_contract()
    entrypoints = contract.get("entrypoints")
    patterns = contract.get("legacy_plaintext_paths")
    if not isinstance(entrypoints, list) or patterns != []:
        raise SystemExit(
            "provider credential contract requires entrypoints and zero legacy_plaintext_paths"
        )
    if contract.get("credential_owner") != (
        "apps.config_center.infrastructure.secret_models.ConfigCenterSecretModel"
    ):
        raise SystemExit("provider credential owner must be Config Center")

    violations = _entrypoint_exists(
        [dict(entry) for entry in entrypoints if isinstance(entry, dict)]
    )
    for path in _production_files():
        violations.extend(_scan_file(path))
    if violations:
        print(json.dumps(violations, ensure_ascii=False, indent=2))
        return 1
    print(f"Data Center provider credential inventory: {len(entrypoints)} entries validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
