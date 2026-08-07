"""Contracts for app-aware incremental Domain coverage selection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_incremental_domain_coverage.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_incremental_domain_coverage", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("incremental Domain coverage runner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_domain_coverage_includes_shared_and_changed_app_tests(tmp_path: Path) -> None:
    """Changed app Domain code must run its own unit tests, not only shared tests."""

    runner = _load_script()
    for relative in (
        "tests/unit/domain",
        "tests/unit/fixed_income",
        "apps/fixed_income/tests",
    ):
        (tmp_path / relative).mkdir(parents=True)

    targets = runner.select_domain_test_targets(
        ["apps.fixed_income.domain.liquidity_premium"],
        root=tmp_path,
    )

    assert targets == [
        "tests/unit/domain",
        "tests/unit/fixed_income",
        "apps/fixed_income/tests",
    ]


def test_domain_coverage_command_keeps_threshold_and_exact_modules(tmp_path: Path) -> None:
    """The runner must preserve the configured threshold and exact coverage targets."""

    runner = _load_script()
    (tmp_path / "tests/unit/domain").mkdir(parents=True)

    command = runner.build_pytest_command(
        ["apps.fixed_income.domain.liquidity_premium"],
        fail_under=70,
        root=tmp_path,
    )

    assert "--cov-fail-under=70" in command
    assert "--cov=apps.fixed_income.domain.liquidity_premium" in command
    assert command.count("tests/unit/domain") == 1
