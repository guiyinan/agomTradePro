"""Boundary contracts for Strategy SDK application services."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.strategy.application import interface_services
from apps.strategy.domain.entities import StrategyExecutionResult
from core.exceptions import DataValidationError


def test_execute_rejects_inactive_strategy_before_loading_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment_loader_called = False

    def load_assignments(strategy_id: int) -> list[object]:
        nonlocal assignment_loader_called
        assignment_loader_called = True
        return []

    monkeypatch.setattr(interface_services, "strategy_is_active", lambda strategy_id: False)
    monkeypatch.setattr(
        interface_services,
        "list_active_assignments_for_strategy",
        load_assignments,
    )

    with pytest.raises(ValueError, match="inactive"):
        interface_services.execute_strategy_for_assignments(strategy_id=7)

    assert assignment_loader_called is False


def test_execute_rejects_mismatched_or_malformed_executor_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment = SimpleNamespace(portfolio_id=11)
    result = StrategyExecutionResult(
        strategy_id=7,
        portfolio_id=12,
        execution_time=datetime.now(UTC),
        execution_duration_ms=10,
        signals=[],
        is_success=True,
    )
    executor = SimpleNamespace(execute_strategy=lambda strategy_id, portfolio_id: result)
    monkeypatch.setattr(interface_services, "strategy_is_active", lambda strategy_id: True)
    monkeypatch.setattr(
        interface_services,
        "list_active_assignments_for_strategy",
        lambda strategy_id: [assignment],
    )
    monkeypatch.setattr(interface_services, "build_strategy_executor", lambda: executor)

    with pytest.raises(DataValidationError) as exc_info:
        interface_services.execute_strategy_for_assignments(strategy_id=7)

    assert exc_info.value.code == "INVALID_STRATEGY_EXECUTION_RESULT"
    assert exc_info.value.details["actual_portfolio_id"] == 12

    result.portfolio_id = 11
    result.execution_duration_ms = -1
    with pytest.raises(DataValidationError, match="无效的执行结果"):
        interface_services.execute_strategy_for_assignments(strategy_id=7)


@pytest.mark.parametrize("signals", ["not-a-list", [1], [{"status": "generated"}, "bad"]])
def test_signal_reads_reject_corrupt_persisted_json(
    monkeypatch: pytest.MonkeyPatch,
    signals: object,
) -> None:
    log = SimpleNamespace(
        id=91,
        portfolio_id=11,
        execution_time=datetime.now(UTC),
        execution_duration_ms=10,
        signals_generated=signals,
        is_success=True,
    )
    monkeypatch.setattr(
        interface_services,
        "list_execution_logs_by_strategy",
        lambda strategy_id, limit=100: [log],
    )

    with pytest.raises(DataValidationError) as exc_info:
        interface_services.list_strategy_signal_payloads(strategy_id=7)

    assert exc_info.value.code == "INVALID_STRATEGY_EXECUTION_LOG"
    assert exc_info.value.details["execution_log_id"] == 91


def test_performance_rejects_negative_persisted_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = SimpleNamespace(
        id=92,
        portfolio_id=11,
        execution_time=datetime.now(UTC),
        execution_duration_ms=-1,
        signals_generated=[],
        is_success=True,
    )
    monkeypatch.setattr(
        interface_services,
        "list_execution_logs_by_strategy",
        lambda strategy_id, limit=100: [log],
    )

    with pytest.raises(DataValidationError, match="无效耗时"):
        interface_services.get_strategy_performance_payload(strategy_id=7)
