"""Tests for the versioned Data Center catalog manifests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    script = _ROOT / "scripts" / "check_data_center_catalog_contracts.py"
    spec = importlib.util.spec_from_file_location("check_data_center_catalog_contracts", script)
    if spec is None or spec.loader is None:
        raise AssertionError("catalog checker cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_canonical_datasets_have_versioned_manifests() -> None:
    """D0-D9 must each have a schema, provider binding, and publish policy."""

    _load_checker().validate()
