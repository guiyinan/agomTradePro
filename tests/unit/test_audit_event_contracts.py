from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.check_audit_event_contracts import (
    DEFAULT_REGISTRY_PATH,
    load_registry,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[2]


def test_registry_is_valid() -> None:
    """The active registry is canonical and all event test references resolve."""

    registry = load_registry(DEFAULT_REGISTRY_PATH)
    violations = validate_registry(registry, project_root=ROOT)

    assert violations == []
    assert registry["status"] == "active"
    assert registry["implementation_status"] == "wired"
    assert len(registry["events"]) >= 20
    assert len(registry["inventory"]) == 6
    assert {item["category"] for item in registry["inventory"]} == {
        "system.operation",
        "system.security",
        "system.configuration",
        "system.task",
        "decision.governance",
        "execution.control",
    }


def test_duplicate_event_type_and_unknown_reason_are_rejected() -> None:
    """The guard rejects taxonomy collisions and non-canonical reason codes."""

    registry = copy.deepcopy(load_registry(DEFAULT_REGISTRY_PATH))
    registry["events"].append(copy.deepcopy(registry["events"][0]))
    registry["events"][-1]["reason_codes"] = ["Not Canonical"]

    violations = validate_registry(registry, project_root=ROOT)
    codes = {violation.code for violation in violations}

    assert "duplicate_event_type" in codes
    assert "reason_codes" in codes


def test_active_event_requires_wired_implementation() -> None:
    """An active event cannot claim a non-wired implementation."""

    registry = copy.deepcopy(load_registry(DEFAULT_REGISTRY_PATH))
    registry["events"][0]["implementation_status"] = "not_wired"

    violations = validate_registry(registry, project_root=ROOT)

    assert any(violation.code == "active_not_wired" for violation in violations)


def test_registry_file_is_json_and_contains_only_contract_data() -> None:
    """The checked-in registry remains deterministic JSON, not runtime evidence."""

    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))

    assert payload["status"] == "active"
    assert payload["implementation_status"] == "wired"
    assert all(event["status"] == "active" for event in payload["events"])
    assert all(event["implementation_status"] == "wired" for event in payload["events"])


def test_inventory_source_file_is_required() -> None:
    """An inventory-only category cannot point at a missing source file."""

    registry = load_registry(DEFAULT_REGISTRY_PATH)
    registry["inventory"][0]["source_files"] = ["apps/audit/does_not_exist.py"]

    violations = validate_registry(registry, project_root=ROOT)

    assert any(violation.code == "inventory_source_missing" for violation in violations)
