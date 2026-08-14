#!/usr/bin/env python3
"""Validate the shadow system-audit event registry.

This M0 guard validates only the machine contract.  It deliberately does not
claim that any event is emitted, persisted, or wired into production.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "governance" / "audit_event_contracts.json"
_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_-]+)+$")
_REASON_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_OWNER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_DETAIL_SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_-]+)+$")


@dataclass(frozen=True)
class AuditEventContractViolation:
    """One malformed registry entry or missing test reference."""

    code: str
    message: str
    path: str


def _violation(code: str, message: str, path: str) -> AuditEventContractViolation:
    return AuditEventContractViolation(code=code, message=message, path=path)


def _is_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(_is_string(item) for item in value)


def _test_reference_exists(project_root: Path, reference: str) -> bool:
    path_text, separator, _symbol = reference.partition("::")
    if not separator or not path_text:
        return False
    path = project_root / path_text
    return path.is_file()


def load_registry(path: Path) -> dict[str, Any]:
    """Load one JSON registry and require a top-level object."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("audit event registry must be a JSON object")
    return payload


def validate_registry(
    registry: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[AuditEventContractViolation]:
    """Return all deterministic registry violations without importing Django."""

    violations: list[AuditEventContractViolation] = []

    if registry.get("schema_version") != 1:
        violations.append(
            _violation("schema_version", "schema_version must be 1", "schema_version")
        )
    if registry.get("owner") != "audit":
        violations.append(_violation("owner", "registry owner must be audit", "owner"))
    if registry.get("status") not in {"shadow", "active"}:
        violations.append(_violation("status", "status must be shadow or active", "status"))
    if registry.get("implementation_status") not in {"registry_only", "wired"}:
        violations.append(
            _violation(
                "implementation_status",
                "implementation_status must be registry_only or wired",
                "implementation_status",
            )
        )

    allowed_categories = registry.get("allowed_categories")
    allowed_policies = registry.get("allowed_write_policies")
    allowed_severities = registry.get("allowed_severities")
    allowed_outcomes = registry.get("allowed_outcomes")
    allowed_correlations = registry.get("allowed_correlations")
    for name, value in (
        ("allowed_categories", allowed_categories),
        ("allowed_write_policies", allowed_policies),
        ("allowed_severities", allowed_severities),
        ("allowed_outcomes", allowed_outcomes),
        ("allowed_correlations", allowed_correlations),
    ):
        if not _is_string_list(value) or not value:
            violations.append(
                _violation("allowlist", f"{name} must be a non-empty string list", name)
            )

    events = registry.get("events")
    if not isinstance(events, list) or not events:
        violations.append(_violation("events", "events must be a non-empty list", "events"))
        return violations

    inventory = registry.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        violations.append(
            _violation("inventory", "inventory must be a non-empty list", "inventory")
        )
        inventory = []
    seen_inventory_categories: set[str] = set()
    for index, item in enumerate(inventory):
        path = f"inventory[{index}]"
        if not isinstance(item, dict):
            violations.append(_violation("inventory", "inventory entry must be an object", path))
            continue
        category = item.get("category")
        if not isinstance(category, str) or category not in (
            allowed_categories if isinstance(allowed_categories, list) else []
        ):
            violations.append(
                _violation("inventory_category", "category is not allowlisted", f"{path}.category")
            )
        elif category in seen_inventory_categories:
            violations.append(
                _violation(
                    "duplicate_inventory_category",
                    "inventory category is duplicated",
                    f"{path}.category",
                )
            )
        else:
            seen_inventory_categories.add(category)
        owner = item.get("owner")
        if not isinstance(owner, str) or _OWNER_PATTERN.fullmatch(owner) is None:
            violations.append(
                _violation("inventory_owner", "owner is not canonical", f"{path}.owner")
            )
        if item.get("status") != "inventory_only":
            violations.append(
                _violation(
                    "inventory_status",
                    "inventory status must be inventory_only",
                    f"{path}.status",
                )
            )
        if item.get("event_contract_status") != "pending":
            violations.append(
                _violation(
                    "inventory_event_status",
                    "inventory event_contract_status must be pending",
                    f"{path}.event_contract_status",
                )
            )
        source_files = item.get("source_files")
        if not _is_string_list(source_files) or not source_files:
            violations.append(
                _violation(
                    "inventory_sources",
                    "source_files must be non-empty",
                    f"{path}.source_files",
                )
            )
        else:
            for source_file in source_files:
                source_path = project_root / source_file
                if (
                    Path(source_file).is_absolute()
                    or ".." in Path(source_file).parts
                    or not source_path.is_file()
                ):
                    violations.append(
                        _violation(
                            "inventory_source_missing",
                            "source_files must point to existing repository files",
                            f"{path}.source_files",
                        )
                    )
        next_stage = item.get("next_stage")
        if not isinstance(next_stage, str) or re.fullmatch(r"M[0-9]+", next_stage) is None:
            violations.append(
                _violation("inventory_stage", "next_stage must be M<number>", f"{path}.next_stage")
            )

    seen_event_types: set[str] = set()
    seen_event_categories: set[str] = set()
    for index, event in enumerate(events):
        path = f"events[{index}]"
        if not isinstance(event, dict):
            violations.append(_violation("event_type", "event must be an object", path))
            continue

        event_type = event.get("event_type")
        if not isinstance(event_type, str) or _EVENT_TYPE_PATTERN.fullmatch(event_type) is None:
            violations.append(
                _violation("event_type", "event_type is not canonical", f"{path}.event_type")
            )
        elif event_type in seen_event_types:
            violations.append(
                _violation("duplicate_event_type", "event_type is duplicated", f"{path}.event_type")
            )
        else:
            seen_event_types.add(event_type)

        category = event.get("category")
        if not isinstance(category, str) or category not in (
            allowed_categories if isinstance(allowed_categories, list) else []
        ):
            violations.append(
                _violation("category", "category is not allowlisted", f"{path}.category")
            )
        else:
            seen_event_categories.add(category)
        owner = event.get("owner")
        if not isinstance(owner, str) or _OWNER_PATTERN.fullmatch(owner) is None:
            violations.append(_violation("event_owner", "owner is not canonical", f"{path}.owner"))
        status = event.get("status")
        if status not in {"planned", "active", "retired"}:
            violations.append(
                _violation(
                    "event_status", "status must be planned, active, or retired", f"{path}.status"
                )
            )
        implementation_status = event.get("implementation_status")
        if implementation_status not in {"not_wired", "wired"}:
            violations.append(
                _violation(
                    "event_implementation_status",
                    "implementation_status must be not_wired or wired",
                    f"{path}.implementation_status",
                )
            )
        policy = event.get("write_policy")
        if policy not in (allowed_policies if isinstance(allowed_policies, list) else []):
            violations.append(
                _violation(
                    "write_policy", "write_policy is not allowlisted", f"{path}.write_policy"
                )
            )
        severity = event.get("severity")
        if severity not in (allowed_severities if isinstance(allowed_severities, list) else []):
            violations.append(
                _violation("severity", "severity is not allowlisted", f"{path}.severity")
            )
        outcomes = event.get("outcomes")
        if not _is_string_list(outcomes) or not outcomes:
            violations.append(
                _violation(
                    "outcomes", "outcomes must be a non-empty string list", f"{path}.outcomes"
                )
            )
        elif any(
            outcome not in (allowed_outcomes if isinstance(allowed_outcomes, list) else [])
            for outcome in outcomes
        ):
            violations.append(
                _violation("outcomes", "outcome is not allowlisted", f"{path}.outcomes")
            )
        correlations = event.get("required_correlations")
        if not _is_string_list(correlations):
            violations.append(
                _violation(
                    "correlations",
                    "required_correlations must be a string list",
                    f"{path}.required_correlations",
                )
            )
        elif any(
            item not in (allowed_correlations if isinstance(allowed_correlations, list) else [])
            for item in correlations
        ):
            violations.append(
                _violation(
                    "correlations",
                    "required correlation is not allowlisted",
                    f"{path}.required_correlations",
                )
            )
        detail_schema = event.get("detail_schema")
        if (
            not isinstance(detail_schema, str)
            or _DETAIL_SCHEMA_PATTERN.fullmatch(detail_schema) is None
        ):
            violations.append(
                _violation(
                    "detail_schema", "detail_schema is not canonical", f"{path}.detail_schema"
                )
            )
        reason_codes = event.get("reason_codes")
        if not _is_string_list(reason_codes) or not reason_codes:
            violations.append(
                _violation(
                    "reason_codes",
                    "reason_codes must be a non-empty string list",
                    f"{path}.reason_codes",
                )
            )
        elif any(_REASON_CODE_PATTERN.fullmatch(code) is None for code in reason_codes):
            violations.append(
                _violation("reason_codes", "reason_code is not canonical", f"{path}.reason_codes")
            )
        test_contract = event.get("test_contract")
        if not isinstance(test_contract, str) or not _test_reference_exists(
            project_root, test_contract
        ):
            violations.append(
                _violation(
                    "test_contract",
                    "test_contract file reference is missing",
                    f"{path}.test_contract",
                )
            )

        if status == "active" and implementation_status != "wired":
            violations.append(
                _violation(
                    "active_not_wired",
                    "active events must declare implementation_status=wired",
                    path,
                )
            )
        if implementation_status == "wired" and status != "active":
            violations.append(
                _violation(
                    "wired_not_active",
                    "wired events must declare status=active",
                    path,
                )
            )

    if registry.get("status") == "active" and registry.get("implementation_status") != "wired":
        violations.append(
            _violation(
                "active_registry_not_wired",
                "active registry must declare implementation_status=wired",
                "implementation_status",
            )
        )
    allowlisted_categories = (
        set(allowed_categories) if isinstance(allowed_categories, list) else set()
    )
    covered_categories = seen_event_categories | seen_inventory_categories
    for category in sorted(allowlisted_categories - covered_categories):
        violations.append(
            _violation(
                "category_uncovered",
                "every allowlisted category needs an event contract or inventory entry",
                category,
            )
        )
    for category in sorted(covered_categories - allowlisted_categories):
        violations.append(
            _violation("category_unknown", "event/inventory category is not allowlisted", category)
        )
    return violations


def main() -> int:
    """Validate the configured registry and return a CI-friendly status."""

    parser = argparse.ArgumentParser(description="Check system audit event contracts.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    path = args.registry if args.registry.is_absolute() else PROJECT_ROOT / args.registry
    try:
        registry = load_registry(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        violation = _violation("registry", str(exc), str(path))
        violations = [violation]
    else:
        violations = validate_registry(registry, project_root=PROJECT_ROOT)

    if args.format == "json":
        print(
            json.dumps(
                [violation.__dict__ for violation in violations], ensure_ascii=False, indent=2
            )
        )
    else:
        if violations:
            print(f"Audit event contract violations: {len(violations)}")
            for violation in violations:
                print(f"- {violation.code}: {violation.path} - {violation.message}")
        else:
            event_count = len(registry.get("events", [])) if "registry" in locals() else 0
            print(
                "Audit event contracts OK: "
                f"events={event_count}; status={registry.get('status', 'unknown')}; "
                f"implementation={registry.get('implementation_status', 'unknown')}"
            )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
