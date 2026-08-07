from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_backtest_compatibility_wrapper_is_deleted() -> None:
    assert not (ROOT / "scripts/run_backtest.py").exists()


def test_seed_historical_compatibility_wrapper_is_deleted() -> None:
    assert not (ROOT / "scripts/seed_historical.py").exists()


def test_retired_wrappers_have_canonical_management_commands() -> None:
    assert (ROOT / "apps/backtest/management/commands/run_backtest.py").is_file()
    assert (ROOT / "apps/macro/management/commands/sync_macro_data.py").is_file()


def test_synthetic_backtest_validator_is_fail_closed() -> None:
    module = _load("validate_backtest_tombstone", "scripts/validate_backtest.py")

    with pytest.raises(SystemExit, match="synthetic prices"):
        module.main([])


def test_obsolete_adapter_smoke_script_is_deleted() -> None:
    assert not (ROOT / "scripts/test_adapters.py").exists()
