"""Tests for the P0 MCP Evidence semantic output freeze."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.check_mcp_evidence_output_surfaces import load_inventory, validate_inventory


def test_repository_mcp_evidence_surface_freeze_is_exact() -> None:
    assert validate_inventory(*load_inventory()) == {
        "surface_count": 18,
        "tagged_read_count": 11,
        "broker_native_count": 6,
        "integrated_count": 0,
        "disabled_count": 6,
    }


def test_guard_rejects_missing_p0_surface() -> None:
    closure, surfaces = load_inventory()

    with pytest.raises(ValueError, match="unclassified P0 MCP Evidence outputs"):
        validate_inventory(closure, surfaces[1:])


def test_guard_rejects_stale_p0_surface() -> None:
    closure, surfaces = load_inventory()
    stale = replace(surfaces[0], capability_key="alpha.read.stale")

    with pytest.raises(ValueError, match="unclassified P0 MCP Evidence outputs"):
        validate_inventory(closure, (stale, *surfaces[1:]))


def test_guard_rejects_output_schema_drift() -> None:
    closure, surfaces = load_inventory()
    changed = replace(surfaces[0], output_schema_sha256="0" * 64)

    with pytest.raises(ValueError, match="output contract changed"):
        validate_inventory(closure, (changed, *surfaces[1:]))


def test_guard_rejects_tui_action_closure_drift() -> None:
    closure, surfaces = load_inventory()
    changed = dict(closure)
    changed["evidence_binding_count"] = 1

    with pytest.raises(ValueError, match="read-action closure changed"):
        validate_inventory(changed, surfaces)


def test_decision_evidence_tag_is_recorded_as_overclaim() -> None:
    _, surfaces = load_inventory()
    surface = next(
        item for item in surfaces if item.capability_key == "equity.read.research_snapshot"
    )

    assert surface.current_gate_state == "semantic_tag_overclaims_contract"


def test_unbound_terminal_result_bridge_is_disabled() -> None:
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

    registry = CapabilityRegistryLoader().build_registry()
    bridge = registry["terminal.read.user_action_result"]

    assert bridge.enabled is False


def test_decision_facing_broker_native_reads_are_disabled() -> None:
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

    registry = CapabilityRegistryLoader().build_registry()
    blocked = {
        "broker_execution.read.overview",
        "broker_execution.read.order_catalog",
        "broker_execution.read.connection_status",
        "broker_execution.read.reconciliation_catalog",
        "broker_execution.read.audit_catalog",
    }

    assert all(registry[key].enabled is False for key in blocked)
    order_detail = registry["broker_execution.read.order_detail"]
    assert order_detail.enabled is True
    assert order_detail.output_schema["additionalProperties"] is False


def test_governed_broker_order_detail_is_display_only_not_evidence_integrated() -> None:
    _, surfaces = load_inventory()
    order_detail = next(
        item for item in surfaces if item.capability_key == "broker_execution.read.order_detail"
    )

    assert order_detail.current_gate_state == ("legacy_evidence_wrapped_display_only_native")
