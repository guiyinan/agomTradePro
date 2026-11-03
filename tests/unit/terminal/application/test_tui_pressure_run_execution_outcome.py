"""Task completion follows persisted pressure evidence, not its risk verdict."""

from __future__ import annotations

import pytest

from apps.terminal.application.tui_workbench_execution import TuiWorkbenchExecutionMixin

_PRESSURE_ACTION = "simulated-trading.portfolio-pressure-run"
_REPORT_ACTION = "simulated-trading.portfolio-risk-report"


def _report(
    *,
    persisted: object = False,
    include_persisted: bool = True,
    risk_outcome: str = "unknown",
) -> dict[str, object]:
    """Build one risk report with independently controlled execution evidence."""

    details: dict[str, object] = {}
    if include_persisted:
        details["run_evidence_persisted"] = persisted
    return {
        "outcome": risk_outcome,
        "checks": [
            {
                "dimension": "exit_pressure",
                "status": risk_outcome,
                "details": details,
            }
        ],
    }


def _execution_outcome(
    payload: object,
    *,
    action_key: str = _PRESSURE_ACTION,
    status_code: int = 200,
) -> str:
    """Call the workbench's bounded execution outcome mapping."""

    service = TuiWorkbenchExecutionMixin()
    return service._execution_outcome(payload, status_code, action_key=action_key)


@pytest.mark.parametrize("persisted", [False, None, "true", 1])
def test_pressure_task_blocks_when_persistence_flag_is_not_exact_true(
    persisted: object,
) -> None:
    """False and malformed persistence evidence never produces task success."""

    assert _execution_outcome(_report(persisted=persisted)) == "blocked"


def test_pressure_task_blocks_when_persistence_evidence_is_missing_or_ambiguous() -> None:
    """Missing reports, missing flags, and duplicate pressure checks fail closed."""

    assert _execution_outcome(_report(include_persisted=False)) == "blocked"
    assert _execution_outcome({"outcome": "unknown", "checks": []}) == "blocked"
    duplicate = _report(persisted=True)
    duplicate_checks = duplicate["checks"]
    assert isinstance(duplicate_checks, list)
    duplicate["checks"] = duplicate_checks * 2
    assert _execution_outcome(duplicate) == "blocked"


def test_pressure_task_reads_persistence_from_an_owner_data_envelope() -> None:
    """A transport wrapper cannot hide an unpersisted nested report."""

    payload = {"outcome": "success", "data": _report(persisted=False)}

    assert _execution_outcome(payload) == "blocked"


@pytest.mark.parametrize("risk_outcome", ["blocked", "partial", "unknown"])
def test_saved_pressure_run_completes_independently_of_risk_verdict(
    risk_outcome: str,
) -> None:
    """A saved analysis is a completed command even when its risk verdict is adverse."""

    assert _execution_outcome(_report(persisted=True, risk_outcome=risk_outcome)) == "success"


def test_pressure_transport_errors_keep_the_existing_failure_outcome() -> None:
    """An HTTP error remains failed even if its body claims that evidence exists."""

    assert _execution_outcome(_report(persisted=True), status_code=409) == "failed"


def test_read_only_portfolio_risk_report_does_not_use_pressure_persistence_gate() -> None:
    """The read-only risk report keeps its existing generic outcome semantics."""

    assert (
        _execution_outcome(
            _report(persisted=False, risk_outcome="unknown"),
            action_key=_REPORT_ACTION,
        )
        == "success"
    )


def test_other_actions_keep_their_published_owner_outcome() -> None:
    """The pressure persistence rule does not change other action outcomes."""

    assert (
        _execution_outcome(
            {"outcome": "partial"},
            action_key="sample.other-action",
        )
        == "partial"
    )
