"""Tests for the deterministic Data Center entrypoint inventory."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "data_center_entrypoint_inventory.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_center_entrypoint_inventory", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Data Center entrypoint inventory script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def inventory_payload() -> tuple[ModuleType, dict[str, object]]:
    """Build the repository-wide AST inventory once for this test module."""

    inventory = _load_script()
    return inventory, inventory.build_inventory()


def test_inventory_covers_every_governed_invocation_category(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    inventory, payload = inventory_payload

    assert inventory.validate_inventory(payload) == []
    assert set(payload["counts"]["by_category"]) == inventory.REQUIRED_CATEGORIES
    assert set(payload["counts"]["by_status"]) == {
        "active_public",
        "adjacent_operational",
        "compatibility",
        "candidate-review",
    }


def test_inventory_has_no_unreviewed_discovery_and_preserves_evidence(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    _inventory, first = inventory_payload

    ids = [entry["id"] for entry in first["entries"]]
    assert len(ids) == len(set(ids))
    assert first["counts"]["by_status"]["candidate-review"] == 0
    assert all(entry["status"] != "candidate-review" for entry in first["entries"])
    assert all(entry["evidence"] for entry in first["entries"])


def test_generated_manifest_matches_static_discovery(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    inventory, payload = inventory_payload
    expected = inventory._canonical_json(payload)

    assert (ROOT / "governance" / "data_center_entrypoints.json").read_text(
        encoding="utf-8"
    ) == expected
