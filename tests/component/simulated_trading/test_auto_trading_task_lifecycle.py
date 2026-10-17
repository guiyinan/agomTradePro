"""Run the actual Celery task and Task Monitor lifecycle against test storage.

The engine and external composition are replaced, while Celery apply/signals,
attempt identity, monitor use case/repository and public projection are real.
No broker delivery, external backend, provider or order execution is involved.
"""

from __future__ import annotations

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from celery.backends.cache import CacheBackend

from apps.simulated_trading.application import tasks
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
)
from apps.task_monitor.application import tasks as monitor_tasks
from apps.task_monitor.application.dtos import project_task_business_result
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.domain.entities import TaskStatus
from apps.task_monitor.infrastructure.repositories import DjangoTaskRecordRepository

pytestmark = pytest.mark.django_db


def _outcome(kind: str, *, large: bool = False) -> AccountAutoTradingOutcome:
    """Build explicit known and unknown engine results without fake trade rows."""

    if kind == "success":
        return AccountAutoTradingOutcome(17, 1, 0)
    if kind == "noop":
        return AccountAutoTradingOutcome(17, 0, 0)
    blocked = kind == "blocked"
    issue = AutoTradingIssue(
        kind=AutoTradingIssueKind.BLOCKED if blocked else AutoTradingIssueKind.FAILED,
        stage="local_fixture",
        code="LOCAL_OUTCOME_UNAVAILABLE",
        effects_indeterminate=kind == "unknown",
    )
    return AccountAutoTradingOutcome(
        17, 1 if kind == "partial" else 0, 0, (issue,) * (100 if large else 1)
    )


def _engine_boundary(monkeypatch: pytest.MonkeyPatch, result: AccountAutoTradingOutcome) -> Mock:
    """Keep the task orchestrator real and isolate all engine construction I/O."""

    for name in (
        "get_simulated_account_repository",
        "get_simulated_position_repository",
        "get_simulated_trade_repository",
        "get_simulated_fee_config_repository",
        "get_signal_repository",
        "get_asset_pool_query_repository",
        "ExecuteBuyOrderUseCase",
        "ExecuteSellOrderUseCase",
        "GetAccountPerformanceUseCase",
        "UnifiedPriceService",
        "AssetPoolQueryService",
        "build_decision_rhythm_exit_advisor",
        "build_decision_execution_link_recorder",
    ):
        monkeypatch.setattr(tasks, name, Mock(return_value=object()))
    engine = Mock(run_daily_trading=Mock(return_value={17: result}))
    monkeypatch.setattr(tasks, "AutoTradingEngine", Mock(return_value=engine))
    return engine


@pytest.mark.parametrize("kind", ["success", "noop", "partial", "blocked", "failed", "unknown"])
def test_actual_task_signals_persist_business_outcome_and_unknown_counts(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A completed Celery apply retains its distinct business outcome in storage."""

    result = _outcome(kind)
    engine = _engine_boundary(monkeypatch, result)
    repository = DjangoTaskRecordRepository()
    monkeypatch.setattr(monitor_tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(
        monitor_tasks, "get_use_case", lambda: RecordTaskExecutionUseCase(repository=repository)
    )
    task = tasks.daily_auto_trading_task
    monkeypatch.setattr(task, "backend", CacheBackend(app=task.app, backend="memory"))
    retry = Mock(side_effect=AssertionError("an entered engine cannot be retried as a batch"))
    monkeypatch.setattr(task, "retry", retry)
    task_id = "ash-auto-outcome-" + uuid4().hex

    execution = task.apply(
        kwargs={"trade_date": "2026-10-16", "account_ids": [17]}, task_id=task_id, throw=True
    )
    record = repository.get_by_task_id(task_id)

    assert execution.state == "SUCCESS"
    assert record is not None and record.attempt_id
    assert record.started_at is not None and record.finished_at is not None
    assert record.status is (
        TaskStatus.FAILURE if kind in {"failed", "unknown"} else TaskStatus.SUCCESS
    )
    projection = project_task_business_result(record.result)
    assert projection.outcome == result.outcome.value
    assert projection.business_success is (kind in {"success", "noop"})
    assert projection.requested == 1
    assert projection.succeeded == (1 if kind in {"success", "noop"} else 0)
    assert projection.failed == (0 if kind in {"success", "noop"} else 1)
    assert projection.stored == result.stored
    assert projection.counts_unavailable is result.counts_unavailable
    assert projection.count_unit == "account"
    assert projection.stored_count_unit == "trade"
    assert projection.stable_error_code == (
        result.reason_code or (result.issues[0].code if result.issues else None)
    )
    engine.run_daily_trading.assert_called_once()
    retry.assert_not_called()


def test_large_actual_task_result_keeps_explicit_unknown_count_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The monitor's bounded JSON must retain explicit unknown-write semantics."""

    engine = _engine_boundary(monkeypatch, _outcome("unknown", large=True))
    repository = DjangoTaskRecordRepository()
    monkeypatch.setattr(monitor_tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(
        monitor_tasks, "get_use_case", lambda: RecordTaskExecutionUseCase(repository=repository)
    )
    task = tasks.daily_auto_trading_task
    monkeypatch.setattr(task, "backend", CacheBackend(app=task.app, backend="memory"))
    retry = Mock(side_effect=AssertionError("an entered engine cannot be retried as a batch"))
    monkeypatch.setattr(task, "retry", retry)
    task_id = "ash-auto-outcome-large-" + uuid4().hex

    execution = task.apply(
        kwargs={"trade_date": "2026-10-16", "account_ids": [17]}, task_id=task_id, throw=True
    )
    record = repository.get_by_task_id(task_id)

    assert execution.state == "SUCCESS"
    assert len(json.dumps(execution.result)) > 10_000
    assert record is not None and record.status is TaskStatus.FAILURE
    assert record.result is not None and len(record.result) <= 10_000
    payload = json.loads(record.result)
    assert payload["result_projection"] == "bounded_business_fields"
    projection = project_task_business_result(record.result)
    assert projection.outcome == "failed"
    assert projection.stored is None
    assert projection.counts_unavailable is True
    assert projection.count_unit == "account"
    assert projection.stored_count_unit == "trade"
    assert projection.stable_error_code == "LOCAL_OUTCOME_UNAVAILABLE"
    engine.run_daily_trading.assert_called_once()
    retry.assert_not_called()
