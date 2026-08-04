"""Check that every SystemSettingsModel field has an explicit owner decision.

The singleton is intentionally retained as a compatibility surface while its
fields are moved to narrower Config Center policies.  This checker is static:
it does not import Django, touch the database, or infer ownership from code.
That makes an unregistered field fail in review/CI instead of silently growing
the legacy singleton.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "apps" / "config_center" / "infrastructure" / "models.py"
CONTRACT_PATH = ROOT / "governance" / "runtime_config_contracts.json"
REPLACEMENT_REQUIRED_LIFECYCLES = {"compatibility", "active_compatibility", "state_compatibility"}


def discover_system_settings_fields(model_path: Path = MODEL_PATH) -> tuple[str, ...]:
    """Return Django field names declared directly on ``SystemSettingsModel``."""

    tree = ast.parse(model_path.read_text(encoding="utf-8"), filename=str(model_path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SystemSettingsModel":
            continue
        fields: list[str] = []
        for statement in node.body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            value = statement.value
            if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
                continue
            if not isinstance(value.func, ast.Attribute):
                continue
            if not isinstance(value.func.value, ast.Name) or value.func.value.id != "models":
                continue
            fields.append(target.id)
        return tuple(fields)
    raise ValueError("SystemSettingsModel class not found")


def load_system_settings_contract(contract_path: Path = CONTRACT_PATH) -> dict[str, Any]:
    """Load and return the field-level contract from the governance manifest."""

    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    contract = payload.get("system_settings_field_contract")
    if not isinstance(contract, dict):
        raise ValueError("runtime config contract lacks system_settings_field_contract")
    return contract


def validate_system_settings_contract(
    model_fields: tuple[str, ...],
    contract: dict[str, Any],
) -> dict[str, object]:
    """Validate group coverage and return deterministic audit counts."""

    groups = contract.get("field_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("system_settings_field_contract.field_groups must be non-empty")
    if str(contract.get("owner") or "").strip() != "config_center":
        raise ValueError("SystemSettingsModel physical owner must remain config_center")

    model_set = set(model_fields)
    grouped: list[str] = []
    compatibility_count = 0
    lifecycle_values: set[str] = set()
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError(f"field group {index} must be an object")
        name = str(group.get("name") or "").strip()
        owner = str(group.get("owner") or "").strip()
        lifecycle = str(group.get("lifecycle") or "").strip()
        fields = group.get("fields")
        if not name or not owner or not lifecycle or not isinstance(fields, list) or not fields:
            raise ValueError(f"field group {index} requires name/owner/lifecycle/fields")
        replacement = group.get("replacement")
        if lifecycle in REPLACEMENT_REQUIRED_LIFECYCLES and not str(replacement or "").strip():
            raise ValueError(f"field group {name} requires a replacement decision")
        lifecycle_values.add(lifecycle)
        if lifecycle in REPLACEMENT_REQUIRED_LIFECYCLES:
            compatibility_count += len(fields)
        for field in fields:
            field_name = str(field).strip()
            if not field_name:
                raise ValueError(f"field group {name} contains an empty field")
            grouped.append(field_name)

    grouped_set = set(grouped)
    duplicates = sorted(field for field in grouped_set if grouped.count(field) > 1)
    missing = sorted(model_set - grouped_set)
    unknown = sorted(grouped_set - model_set)
    if duplicates or missing or unknown:
        problems: list[str] = []
        if duplicates:
            problems.append("duplicate=" + ",".join(duplicates))
        if missing:
            problems.append("missing=" + ",".join(missing))
        if unknown:
            problems.append("unknown=" + ",".join(unknown))
        raise ValueError("SystemSettingsModel field contract mismatch: " + "; ".join(problems))

    return {
        "field_count": len(model_fields),
        "group_count": len(groups),
        "compatibility_field_count": compatibility_count,
        "lifecycle_values": tuple(sorted(lifecycle_values)),
    }


def audit_system_settings_contract() -> dict[str, object]:
    """Run the repository-local SystemSettings field contract audit."""

    model_fields = discover_system_settings_fields()
    contract = load_system_settings_contract()
    return validate_system_settings_contract(model_fields, contract)


def main() -> int:
    """Print a machine-readable success summary or fail closed."""

    try:
        report = audit_system_settings_contract()
    except (OSError, SyntaxError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"SystemSettings field contract failed: {exc}") from exc
    print(
        "SystemSettings field contract valid: "
        f"{report['field_count']} fields / {report['group_count']} groups; "
        f"compatibility={report['compatibility_field_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
