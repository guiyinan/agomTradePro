"""Guard the Config Center owner boundary for backup delivery secrets."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "governance" / "backup_delivery_secret_contracts.json"
SOURCE_ROOTS = (ROOT / "apps", ROOT / "core", ROOT / "shared")
LEGACY_ASSIGNMENT_NAMES = {
    "backup_password_encrypted",
    "backup_smtp_password_encrypted",
}
LEGACY_SETTER_NAMES = {"set_backup_password", "set_backup_smtp_password"}
ALLOWED_MODEL_PATH = "apps/config_center/infrastructure/models.py"


def _iter_source_files() -> list[Path]:
    """Return production Python files, excluding migrations and test fixtures."""

    return sorted(
        path
        for source_root in SOURCE_ROOTS
        for path in source_root.rglob("*.py")
        if "migrations" not in path.parts and "tests" not in path.parts
    )


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _legacy_write_violations(path: Path) -> list[str]:
    """Find direct legacy encrypted-column writes outside the owner model."""

    relative = _relative(path)
    if relative == ALLOWED_MODEL_PATH:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in LEGACY_ASSIGNMENT_NAMES:
                    violations.append(f"{relative}:{node.lineno}:{target.id}")
                if isinstance(target, ast.Attribute) and target.attr in LEGACY_ASSIGNMENT_NAMES:
                    violations.append(f"{relative}:{node.lineno}:{target.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in LEGACY_SETTER_NAMES:
                violations.append(f"{relative}:{node.lineno}:{node.func.attr}")
    return violations


def validate() -> list[str]:
    """Return deterministic ownership violations."""

    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    violations: list[str] = []
    if str(payload.get("owner") or "") != "config_center":
        violations.append("contract_owner_invalid")
    refs = payload.get("secret_refs")
    if not isinstance(refs, dict) or set(refs) != {
        "backup.archive_password",
        "backup.smtp_password",
    }:
        violations.append("secret_ref_catalog_invalid")
    for required in payload.get("owner_paths", []):
        if not (ROOT / str(required)).exists():
            violations.append(f"owner_path_missing:{required}")
    violations.extend(
        violation for path in _iter_source_files() for violation in _legacy_write_violations(path)
    )
    return sorted(violations)


def main() -> int:
    """Fail closed when a new direct legacy secret write is introduced."""

    try:
        violations = validate()
    except (OSError, SyntaxError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"backup delivery secret ownership guard failed: {exc}") from exc
    if violations:
        raise SystemExit("Backup delivery secret ownership violations: " + "; ".join(violations))
    print("Backup delivery secret owner: Config Center; legacy writes=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
