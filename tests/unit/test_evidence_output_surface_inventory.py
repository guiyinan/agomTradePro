"""Tests for the first-batch decision-facing output inventory."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.check_evidence_output_surfaces import (
    DEFAULT_INVENTORY,
    load_inventory,
    parse_inventory,
    validate_inventory,
)


def test_repository_evidence_output_inventory_is_exact() -> None:
    assert validate_inventory(load_inventory()) == {
        "surface_count": 41,
        "direct_position_surface_count": 11,
        "marked_surface_count": 32,
        "dynamic_surface_count": 16,
    }


def test_parser_rejects_unclassified_claim_kind() -> None:
    payload = json.loads(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    payload["surfaces"][0]["claim_kind"] = "unclassified"

    with pytest.raises(ValueError, match="unclassified evidence output surface"):
        parse_inventory(payload)


def test_parser_rejects_missing_required_classification_field() -> None:
    payload = json.loads(DEFAULT_INVENTORY.read_text(encoding="utf-8"))
    del payload["surfaces"][0]["method_kind"]

    with pytest.raises(ValueError, match="method_kind must be non-empty text"):
        parse_inventory(payload)


def test_quote_surface_records_legacy_display_only_adapter() -> None:
    inventory = load_inventory()
    quote = next(
        surface
        for surface in inventory.surfaces
        if surface.source_symbol.endswith("::QuoteResponse")
    )

    assert quote.current_gate_state == "legacy_evidence_wrapped_display_only"


def test_guard_rejects_unregistered_marked_surface() -> None:
    inventory = load_inventory()
    retained = tuple(
        surface
        for surface in inventory.surfaces
        if not surface.source_symbol.endswith("::ScenarioProbabilityResearchPacket")
    )

    with pytest.raises(ValueError, match="unclassified marked evidence output surfaces"):
        validate_inventory(replace(inventory, surfaces=retained))


def test_guard_rejects_registered_contract_field_drift() -> None:
    inventory = load_inventory()
    first = inventory.surfaces[0]
    changed = replace(first, required_fields=first.required_fields | {"missing_gate_field"})

    with pytest.raises(ValueError, match="changed evidence output contract"):
        validate_inventory(replace(inventory, surfaces=(changed, *inventory.surfaces[1:])))


def test_guard_rejects_unregistered_dynamic_surface() -> None:
    inventory = load_inventory()
    missing = next(iter(inventory.dynamic_surfaces))

    with pytest.raises(ValueError, match="unclassified dynamic evidence output surfaces"):
        validate_inventory(
            replace(inventory, dynamic_surfaces=inventory.dynamic_surfaces - {missing})
        )


def test_guard_rejects_stale_dynamic_surface() -> None:
    inventory = load_inventory()

    with pytest.raises(ValueError, match="stale dynamic evidence output surfaces"):
        validate_inventory(
            replace(
                inventory,
                dynamic_surfaces=inventory.dynamic_surfaces
                | {"apps/broker_execution/application/query_services.py::Missing.output"},
            )
        )
