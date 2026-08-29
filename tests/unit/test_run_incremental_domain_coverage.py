"""Contracts for app-aware incremental Domain coverage selection."""

from __future__ import annotations

import importlib.util
from configparser import ConfigParser
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_incremental_domain_coverage.py"
COVERAGE_CONFIG = ROOT / "config" / "coverage" / "incremental-domain.coveragerc"


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


def test_domain_coverage_includes_external_unit_tests_with_direct_imports(
    tmp_path: Path,
) -> None:
    """Legacy or cross-app unit tests must contribute when they import the Domain."""

    runner = _load_script()
    (tmp_path / "tests/unit/domain").mkdir(parents=True)
    (tmp_path / "tests/unit/fixed_income").mkdir(parents=True)
    external_test = tmp_path / "tests/unit/risk/test_liquidity_premium.py"
    external_test.parent.mkdir(parents=True)
    external_test.write_text(
        "from apps.fixed_income.domain.liquidity_premium import calculate\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/unit/test_unrelated.py").write_text(
        "from apps.equity.domain.signals import Signal\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/unit/fixed_income/test_owned.py").write_text(
        "import apps.fixed_income.domain\n",
        encoding="utf-8",
    )

    targets = runner.select_domain_test_targets(
        ["apps.fixed_income.domain"],
        root=tmp_path,
    )

    assert targets == [
        "tests/unit/domain",
        "tests/unit/fixed_income",
        "tests/unit/risk/test_liquidity_premium.py",
    ]


def test_domain_coverage_command_keeps_threshold_and_exact_modules(tmp_path: Path) -> None:
    """The runner must preserve the configured threshold and exact coverage targets."""

    runner = _load_script()
    (tmp_path / "tests/unit/domain").mkdir(parents=True)

    command = runner.build_pytest_command(
        "apps.fixed_income.domain",
        fail_under=90,
        root=tmp_path,
    )

    assert "--cov-fail-under=90" in command
    assert "--cov-config=config/coverage/incremental-domain.coveragerc" in command
    assert "--cov=apps.fixed_income.domain" in command
    assert command.count("tests/unit/domain") == 1


def test_domain_coverage_commands_isolate_each_app(tmp_path: Path) -> None:
    """One app's high coverage must not hide another app's regression."""

    runner = _load_script()
    (tmp_path / "tests/unit/domain").mkdir(parents=True)

    commands = runner.build_pytest_commands(
        ["apps.equity.domain", "apps.data_center.domain", "apps.equity.domain"],
        fail_under=90,
        root=tmp_path,
    )

    assert [command[-1] for command in commands] == [
        "--cov=apps.data_center.domain",
        "--cov=apps.equity.domain",
    ]


def test_incremental_config_does_not_inherit_repository_wide_sources() -> None:
    """Unrelated imported apps must not dilute one changed app's coverage."""

    config = ConfigParser()
    assert config.read(COVERAGE_CONFIG, encoding="utf-8") == [str(COVERAGE_CONFIG)]
    assert not config.has_option("run", "source")
    assert not config.getboolean("run", "branch", fallback=False)
