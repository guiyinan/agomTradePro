"""Tests for the governed decision-write surface freeze."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.check_decision_write_surface_freeze import load_inventory, validate_surface_freeze


def test_repository_decision_write_surface_inventory_is_exact() -> None:
    assert validate_surface_freeze(load_inventory()) == {
        "http_surface_count": 54,
        "sdk_surface_count": 15,
    }


def test_guard_rejects_new_unclassified_http_surface() -> None:
    inventory = load_inventory()
    missing = next(iter(inventory.http_surfaces))

    with pytest.raises(ValueError, match="unclassified HTTP mutation surfaces"):
        validate_surface_freeze(
            replace(inventory, http_surfaces=inventory.http_surfaces - {missing})
        )


def test_guard_rejects_stale_sdk_surface() -> None:
    inventory = load_inventory()

    with pytest.raises(ValueError, match="stale SDK mutation surfaces"):
        validate_surface_freeze(
            replace(
                inventory,
                sdk_mutation_surfaces=inventory.sdk_mutation_surfaces
                | {"sdk/agomtradepro/modules/missing.py::Missing.write"},
            )
        )
