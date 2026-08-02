"""Regression tests for the deterministic canonical data-center inventory."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "data_center_architecture_inventory.py"
_ARTIFACT = _ROOT / "governance" / "data_center_architecture_inventory.json"


def _load_inventory_module() -> ModuleType:
    """Load the standalone inventory script without importing the Django project."""

    spec = importlib.util.spec_from_file_location("data_center_architecture_inventory", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("inventory script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_artifact_is_deterministic_and_current() -> None:
    """The committed M0 evidence must match a fresh static scan exactly."""

    module = _load_inventory_module()
    expected = module._canonical_json(module.build_inventory())
    assert _ARTIFACT.read_text(encoding="utf-8") == expected


def test_inventory_separates_sdk_ownership_from_http_review() -> None:
    """Provider SDKs are centralized while generic HTTP callers remain reviewable."""

    module = _load_inventory_module()
    payload = module.build_inventory()
    assert payload["counts"]["provider_imports_outside_data_center"] == 0
    assert payload["counts"]["external_http_imports_for_review"] > 0
    assert "generated_at" not in payload

    artifact = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    assert artifact["counts"] == payload["counts"]
