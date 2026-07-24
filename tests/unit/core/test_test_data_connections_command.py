import io
import json
from pathlib import Path

import pytest
from django.core.management.base import CommandError, OutputWrapper

from core.management.commands.test_data_connections import (
    Command,
    DataConnectionTester,
)

_TEST_METHOD_NAMES = (
    "test_database_connection",
    "test_account_data",
    "test_macro_data_update",
    "test_regime_calculation",
    "test_policy_events",
    "test_investment_signals",
    "test_dashboard_data",
    "test_data_consistency",
)


def _tester(*, results_path: Path | None = None) -> DataConnectionTester:
    return DataConnectionTester(
        OutputWrapper(io.StringIO()),
        results_path=results_path,
    )


def _set_successful_suites(monkeypatch, tester: DataConnectionTester) -> None:
    for method_name in _TEST_METHOD_NAMES:

        def _success(name: str = method_name) -> bool:
            tester.log_result("Test", name, "success")
            return True

        monkeypatch.setattr(tester, method_name, _success)


def test_runner_fails_when_nested_check_logs_error(monkeypatch):
    tester = _tester()
    _set_successful_suites(monkeypatch, tester)

    def _nested_error() -> bool:
        tester.log_result("Macro", "PMI数据更新", "error", "provider unavailable")
        return True

    monkeypatch.setattr(tester, "test_macro_data_update", _nested_error)

    assert tester.run_all_tests() is False


def test_runner_fails_when_suite_returns_without_evidence(monkeypatch):
    tester = _tester()
    _set_successful_suites(monkeypatch, tester)
    monkeypatch.setattr(tester, "test_regime_calculation", lambda: True)

    assert tester.run_all_tests() is False
    assert any(
        result["category"] == "Runner"
        and result["test"] == "Regime判定"
        and result["status"] == "error"
        for result in tester.results
    )


def test_exception_details_redact_credentials():
    tester = _tester()

    tester.log_exception(
        "Provider",
        "connection",
        RuntimeError("api_key=secret-value token:other-secret endpoint failed"),
    )

    details = tester.results[0]["details"]
    assert "secret-value" not in details
    assert "other-secret" not in details
    assert "api_key=<redacted>" in details
    assert "token:<redacted>" in details


def test_results_are_written_with_explicit_overall_status(tmp_path):
    results_path = tmp_path / "diagnostics" / "results.json"
    tester = _tester(results_path=results_path)
    tester.log_result("Database", "connection", "success", "ok")
    tester.log_result("Macro", "sync", "warning", "stale")

    tester.save_results()

    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["overall_success"] is True
    assert payload["success"] == 1
    assert payload["warnings"] == 1
    assert payload["errors"] == 0
    assert not results_path.with_suffix(".json.tmp").exists()


def test_command_raises_command_error_when_any_suite_fails(monkeypatch):
    monkeypatch.setattr(DataConnectionTester, "run_all_tests", lambda self: False)
    command = Command()

    with pytest.raises(CommandError, match="diagnostics failed"):
        command.handle(no_write=True, output=Path("unused.json"))


def test_command_no_write_success_does_not_create_output(monkeypatch, tmp_path):
    monkeypatch.setattr(DataConnectionTester, "run_all_tests", lambda self: True)
    output_path = tmp_path / "must-not-exist.json"

    Command().handle(no_write=True, output=output_path)

    assert not output_path.exists()
