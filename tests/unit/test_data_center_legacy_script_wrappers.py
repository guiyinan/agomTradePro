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


@pytest.mark.parametrize(
    ("module_name", "relative_path", "expected_command"),
    [
        ("run_backtest_wrapper", "scripts/run_backtest.py", "run_backtest"),
    ],
)
def test_simple_legacy_scripts_route_to_canonical_management_commands(
    monkeypatch,
    module_name: str,
    relative_path: str,
    expected_command: str,
) -> None:
    module = _load(module_name, relative_path)
    captured: list[list[str]] = []
    monkeypatch.setattr(
        "django.core.management.execute_from_command_line",
        lambda arguments: captured.append(list(arguments)),
    )

    module.main(["--list"])

    assert captured[0][1] == expected_command
    assert captured[0][-1] == "--list"


def test_seed_historical_translates_legacy_selectors_without_data_access(monkeypatch) -> None:
    module = _load("seed_historical_wrapper", "scripts/seed_historical.py")
    captured: list[list[str]] = []
    monkeypatch.setattr(
        "django.core.management.execute_from_command_line",
        lambda arguments: captured.append(list(arguments)),
    )

    module.main(["--all", "--start", "2020-01-01", "--end", "2024-12-31"])

    arguments = captured[0]
    assert arguments[1] == "sync_macro_data"
    assert "--indicators" in arguments
    assert all(code in arguments for code in ("CN_PMI", "CN_CPI", "CN_PPI", "CN_M2"))
    assert "--all" not in arguments


def test_seed_historical_rejects_retired_check_mode() -> None:
    module = _load("seed_historical_check_tombstone", "scripts/seed_historical.py")

    with pytest.raises(SystemExit, match="test_data_connections"):
        module.main(["--check"])


def test_synthetic_backtest_validator_is_fail_closed() -> None:
    module = _load("validate_backtest_tombstone", "scripts/validate_backtest.py")

    with pytest.raises(SystemExit, match="synthetic prices"):
        module.main([])


def test_obsolete_adapter_smoke_script_is_deleted() -> None:
    assert not (ROOT / "scripts/test_adapters.py").exists()
