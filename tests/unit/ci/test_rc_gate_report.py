"""RC evidence must fail closed without claiming production acceptance."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

import scripts.run_live_server_pytest as live_server_launcher
from scripts.rc_gate_report import REQUIRED_GATES, build_report, main
from scripts.run_live_server_pytest import (
    _build_server_command,
    _request_server_stack_dump,
    _server_stack_dump_signal,
    _validate_summary,
)

ROOT = Path(__file__).resolve().parents[3]


def _results() -> dict[str, object]:
    return {gate.key: {"result": "success"} for gate in REQUIRED_GATES}


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "unknown", None])
def test_required_gate_cannot_pass_without_success(result: object) -> None:
    results = _results()
    results["journey"] = {"result": result}
    report = build_report(results, sha="a" * 40, version="v1-rc1")
    assert report["summary"]["overall_status"] == "blocked"
    assert report["summary"]["passed"] == len(REQUIRED_GATES) - 1
    assert report["production_acceptance"] == "unverified"


@pytest.mark.parametrize("results", [{}, [], None, {"architecture": "success"}])
def test_missing_or_malformed_evidence_blocks_rc(results: object) -> None:
    assert (
        build_report(results, sha="a" * 40, version="rc")["summary"]["overall_status"] == "blocked"
    )


def test_all_ci_gates_pass_without_authorizing_production() -> None:
    report = build_report(_results(), sha="a" * 40, version="rc")
    assert report["summary"]["overall_status"] == "passed"
    assert report["summary"]["passed"] == report["summary"]["total_checks"]
    assert report["production_acceptance"] == "unverified"
    assert report["deployment_authorized"] is False
    assert report["defect_inventory"] == "unverified"


def test_unknown_candidate_cannot_pass() -> None:
    assert (
        build_report(_results(), sha="unknown", version="rc")["summary"]["overall_status"]
        == "blocked"
    )


def test_cli_retains_blocked_report_and_returns_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CI_JOB_RESULTS", "not-json")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    output = tmp_path / "rc.json"
    monkeypatch.setattr("sys.argv", ["rc_gate_report.py", "--output", str(output)])
    assert main() == 1
    assert json.loads(output.read_text())["summary"]["overall_status"] == "blocked"


def test_rc_reuses_all_daily_gates_and_requires_every_result() -> None:
    # BaseLoader keeps the YAML 1.2 Actions key `on` as a string.
    workflow = yaml.load(
        (ROOT / ".github/workflows/rc-gate.yml").read_text(), Loader=yaml.BaseLoader
    )
    jobs = workflow["jobs"]
    summary = jobs["rc-gate-summary"]
    assert set(summary["needs"]) == {gate.key for gate in REQUIRED_GATES}
    assert summary["if"] == "always()"
    for gate in REQUIRED_GATES:
        job = jobs[gate.key]
        assert "continue-on-error" not in job
        if gate.workflow:
            assert job["uses"] == f"./.github/workflows/{gate.workflow}"
            called = yaml.load(
                (ROOT / ".github/workflows" / gate.workflow).read_text(), Loader=yaml.BaseLoader
            )
            assert "workflow_call" in called["on"]
    assert "skip_journey" not in workflow["on"]["workflow_dispatch"].get("inputs", {})
    assert any(
        step.get("env", {}).get("CI_JOB_RESULTS") == "${{ toJSON(needs) }}"
        for step in summary["steps"]
    )


def test_workflow_has_no_independent_rc_threshold_or_fabricated_passes() -> None:
    source = (ROOT / ".github/workflows/rc-gate.yml").read_text()
    assert "cov-fail-under" not in source
    assert "P0=0" not in source
    assert "All checks PASSED" not in source
    fast = (ROOT / ".github/workflows/ci-fast-feedback.yml").read_text()
    assert "--fail-under 90" not in fast


@pytest.mark.parametrize(
    "changes", [{"skipped": 1}, {"failures": 1}, {"errors": 1}, {"total": 0, "executed": 0}]
)
def test_required_journey_rejects_incomplete_execution(changes: dict[str, int]) -> None:
    summary = {"total": 20, "executed": 20, "passed": 20, "skipped": 0, "failures": 0, "errors": 0}
    summary.update(changes)
    with pytest.raises(RuntimeError):
        _validate_summary("rc", summary, 20, require_no_skips=True)


def test_server_command_without_stack_diagnostics_keeps_original_argv() -> None:
    assert _build_server_command("127.0.0.1", 8000, None) == [
        sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8000",
        "--noreload",
        "--nothreading",
    ]


def test_stack_diagnostics_require_a_log_and_posix_signal_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _server_stack_dump_signal(None) is None

    monkeypatch.setattr(live_server_launcher, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(live_server_launcher, "signal", SimpleNamespace(SIGUSR1=10))
    assert _server_stack_dump_signal(tmp_path / "server.log") is None

    monkeypatch.setattr(live_server_launcher, "os", SimpleNamespace(name="posix"))
    assert _server_stack_dump_signal(tmp_path / "server.log") == 10

    monkeypatch.setattr(live_server_launcher, "signal", SimpleNamespace())
    assert _server_stack_dump_signal(tmp_path / "server.log") is None


def test_server_command_registers_stack_diagnostics_in_the_server_process() -> None:
    command = _build_server_command("127.0.0.1", 8000, 10)
    assert command[:2] == [sys.executable, "-c"]
    assert "faulthandler.register(10, all_threads=True, chain=False)" in command[2]
    assert "sys.argv = ['manage.py', 'runserver', '127.0.0.1:8000'" in command[2]
    assert "runpy.run_path('manage.py', run_name='__main__')" in command[2]


@pytest.mark.parametrize(("returncode", "expected"), [(None, True), (0, False), (1, False)])
def test_stack_dump_targets_only_the_still_running_server(
    returncode: int | None, expected: bool
) -> None:
    process = Mock()
    process.poll.return_value = returncode

    assert _request_server_stack_dump(process, 10) is expected
    if expected:
        process.send_signal.assert_called_once_with(10)
    else:
        process.send_signal.assert_not_called()


def test_stack_dump_skips_missing_server_and_missing_signal() -> None:
    assert _request_server_stack_dump(None, 10) is False

    process = Mock()
    assert _request_server_stack_dump(process, None) is False
    process.poll.assert_not_called()
    process.send_signal.assert_not_called()


def test_stack_dump_skips_server_that_exited_before_the_poll() -> None:
    process = Mock()
    process.poll.return_value = 0

    assert _request_server_stack_dump(process, 10) is False
    process.send_signal.assert_not_called()


def test_stack_dump_handles_server_exit_between_poll_and_signal() -> None:
    process = Mock()
    process.poll.return_value = None
    process.send_signal.side_effect = ProcessLookupError

    assert _request_server_stack_dump(process, 10) is False
    process.poll.assert_called_once_with()
    process.send_signal.assert_called_once_with(10)
