from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_data_center_legacy_entrypoints.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_center_legacy_entrypoints", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("legacy entrypoint guard cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_legacy_script_data_center_imports_are_registered() -> None:
    assert _load_guard().validate() == []
