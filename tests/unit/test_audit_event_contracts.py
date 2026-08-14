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
    """The shadow registry is canonical and all event test references resolve."""

    registry = load_registry(DEFAULT_REGISTRY_PATH)
    violations = validate_registry(registry, project_root=ROOT)

    assert violations == []
    assert registry["status"] == "shadow"
    assert registry["implementation_status"] == "registry_only"
    assert len(registry["events"]) >= 20


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
    """A future active event cannot be declared before its implementation exists."""

    registry = copy.deepcopy(load_registry(DEFAULT_REGISTRY_PATH))
    registry["events"][0]["status"] = "active"

    violations = validate_registry(registry, project_root=ROOT)

    assert any(violation.code == "active_not_wired" for violation in violations)


def test_registry_file_is_json_and_contains_only_contract_data() -> None:
    """The checked-in registry remains deterministic JSON, not runtime evidence."""

    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))

    assert payload["status"] == "shadow"
    assert payload["implementation_status"] == "registry_only"
    assert all(event["implementation_status"] == "not_wired" for event in payload["events"])
