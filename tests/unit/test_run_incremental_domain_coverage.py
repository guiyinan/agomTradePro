"""Contracts for app-aware incremental Domain coverage selection."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from configparser import ConfigParser
from pathlib import Path
from types import ModuleType

import pytest

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


def test_run_pytest_commands_isolates_coverage_files_and_returns_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parallel gates must not share one .coverage file and must run every app."""

    runner = _load_script()
    calls: list[tuple[list[str], str]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(command), env["COVERAGE_FILE"]))
        module = command[-1].removeprefix("--cov=")
        returncode = 3 if module == "apps.alpha.domain" else 0
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    commands = [
        ["pytest", "--cov=apps.alpha.domain"],
        ["pytest", "--cov=apps.beta.domain"],
    ]

    returncode = runner.run_pytest_commands(commands, max_workers=2)

    assert returncode == 3
    assert len(calls) == 2
    assert {env for _, env in calls} == {
        str(runner.ROOT / ".coverage.domain-apps.alpha.domain"),
        str(runner.ROOT / ".coverage.domain-apps.beta.domain"),
    }


def test_run_pytest_commands_rejects_command_without_cov_target() -> None:
    """The per-command coverage-file isolation requires a trailing --cov flag."""

    runner = _load_script()
    with pytest.raises(ValueError, match="--cov="):
        runner.run_pytest_commands([["pytest", "tests/"]])


def test_domain_floor_follows_machine_baseline(tmp_path: Path) -> None:
    runner = _load_script()
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"coverage": {"domain_module_minimum": 93.5}}))
    assert runner.load_domain_minimum(path) == 93.5


@pytest.mark.parametrize("value", [True, 0, -1, 101, "90", float("nan")])
def test_invalid_domain_floor_fails_closed(tmp_path: Path, value: object) -> None:
    runner = _load_script()
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"coverage": {"domain_module_minimum": value}}))
    with pytest.raises(ValueError):
        runner.load_domain_minimum(path)


def test_cli_rejects_a_lower_local_floor(monkeypatch) -> None:
    runner = _load_script()
    monkeypatch.setattr(runner, "load_domain_minimum", lambda: 90)
    monkeypatch.setattr("sys.argv", ["runner", "apps.alpha.domain", "--fail-under", "70"])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
