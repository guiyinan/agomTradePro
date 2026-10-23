"""Account periodic-task result and notification contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.account.application import tasks


def _result(
    *,
    triggered: bool = False,
    partial_level: int | None = None,
    execution_status: str = "not_triggered",
) -> SimpleNamespace:
    return SimpleNamespace(
        triggered=triggered,
        check_status="evaluated",
        execution_status=execution_status,
        execution_receipt_id=None,
        reason_code="legacy_automatic_exit_not_qualified" if triggered else None,
        asset_code="000001.SZ",
        position_id=1,
        current_price=10.5,
        price_source="unified_quote",
        price_observed_at=datetime(2026, 4, 1, tzinfo=UTC),
        price_freshness="realtime",
        must_not_use_for_decision=True,
        must_not_execute=True,
        unrealized_pnl_pct=-0.1,
        partial_level=partial_level,
        check_result=SimpleNamespace(trigger_reason="risk threshold", stop_price=10.0),
    )


def test_periodic_risk_tasks_count_trigger_intent_and_blocked_execution(monkeypatch) -> None:
    """Periodic tasks preserve trigger counts without claiming a completed sale."""

    stop_results = [
        _result(triggered=True, execution_status="blocked"),
        _result(),
    ]
    take_results = [_result(triggered=True, partial_level=1, execution_status="blocked")]
    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(check_and_execute_stop_loss=lambda user_id=None: stop_results),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(check_and_execute_take_profit=lambda user_id=None: take_results),
    )
    notification_inputs: list[tuple[str, list[bool], int | None]] = []

    def _capture_notification_input(
        category: str,
        results: list[SimpleNamespace],
        user_id: int | None,
    ) -> None:
        notification_inputs.append((category, [result.triggered for result in results], user_id))

    monkeypatch.setattr(
        tasks,
        "_send_stop_loss_notifications",
        lambda results, user_id=None: _capture_notification_input("stop", results, user_id),
    )
    monkeypatch.setattr(
        tasks,
        "_send_take_profit_notifications",
        lambda results, user_id=None: _capture_notification_input("take", results, user_id),
    )

    stop = tasks.check_stop_loss_task.run(user_id=1)
    take = tasks.check_take_profit_task.run(user_id=1)
    combined = tasks.check_stop_loss_and_take_profit_task.run(user_id=1)
    assert stop["outcome"] == "partial"
    assert stop["checked_count"] == 2
    assert stop["triggered_count"] == 1
    assert stop["executed_count"] == 0
    assert stop["stored"] == 0
    assert take["outcome"] == "blocked"
    assert take["triggered_count"] == 1
    assert take["blocked_count"] == 1
    assert take["stored"] == 0
    assert combined["stop_loss_triggered"] == 1
    assert combined["take_profit_triggered"] == 1
    assert combined["stop_loss_executed"] == 0
    assert combined["take_profit_executed"] == 0
    assert notification_inputs == [
        ("stop", [True, False], 1),
        ("take", [True], 1),
        ("stop", [True, False], 1),
        ("take", [True], 1),
    ]


def test_stop_loss_business_failure_is_redacted_and_marks_unknown_stage(
    monkeypatch, caplog
) -> None:
    """Task results do not leak exception strings or retry an entered stage."""

    secret = "postgresql://user:secret@database.invalid/account"

    def _fail(*, user_id=None):
        del user_id
        raise RuntimeError(secret)

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(check_and_execute_stop_loss=_fail),
    )
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_stop_loss_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stage must not retry")),
    )

    result = tasks.check_stop_loss_task.run(user_id=1)

    assert result["status"] == "error"
    assert result["outcome"] == "failed"
    assert result["stage_unknown_count"] == 1
    assert result["stored"] is None
    assert secret not in caplog.text


def test_combined_setup_retry_precedes_any_stage_and_has_no_checkpoint(monkeypatch) -> None:
    """A second constructor failure retries only before either stage has started."""

    calls: list[str] = []
    captured_retry: dict[str, object] = {}

    def _run_stop_loss(user_id=None):
        del user_id
        calls.append("stop_stage")
        return [_result()]

    def _stop_factory():
        calls.append("stop_setup")
        return SimpleNamespace(check_and_execute_stop_loss=_run_stop_loss)

    def _take_factory():
        calls.append("take_setup")
        raise RuntimeError("setup unavailable")

    def _retry(**kwargs):
        captured_retry.update(kwargs)
        raise RuntimeError("retry scheduled")

    monkeypatch.setattr(tasks, "AutoStopLossUseCase", _stop_factory)
    monkeypatch.setattr(tasks, "AutoTakeProfitUseCase", _take_factory)
    monkeypatch.setattr(tasks.check_stop_loss_and_take_profit_task, "retry", _retry)

    with pytest.raises(RuntimeError, match="retry scheduled"):
        tasks.check_stop_loss_and_take_profit_task.run(user_id=1)

    assert calls == ["stop_setup", "take_setup"]
    assert captured_retry["kwargs"] == {"user_id": 1, "checkpoint": None}


def test_notification_helpers_use_blocked_observation_language(monkeypatch) -> None:
    """Owner notices report trigger observations and never claim an automatic close."""

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda _position_id: {"user_id": 7, "user_email": "owner@example.test"},
    )
    monkeypatch.setattr(tasks, "send_mail", lambda **kwargs: sent.append(kwargs))

    tasks._send_stop_loss_notifications(
        [_result(triggered=True, execution_status="blocked")], user_id=8
    )
    assert sent == []
    tasks._send_stop_loss_notifications(
        [_result(triggered=True, execution_status="blocked")], user_id=7
    )
    tasks._send_take_profit_notifications(
        [_result(triggered=True, partial_level=1, execution_status="blocked")], user_id=7
    )

    assert len(sent) == 2
    for item in sent:
        assert "系统未提交自动卖出" in item["message"]
        assert "未确认成交或平仓" in item["message"]
        assert "平仓成功" not in item["message"]


def test_notification_lookup_failure_is_isolated(monkeypatch) -> None:
    """An owner contact lookup failure does not alter task execution state."""

    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda _position_id: (_ for _ in ()).throw(RuntimeError("lookup failed")),
    )
    tasks._send_stop_loss_notifications(
        [_result(triggered=True, execution_status="blocked")], user_id=7
    )
    tasks._send_take_profit_notifications(
        [_result(triggered=True, partial_level=1, execution_status="blocked")], user_id=7
    )


def test_volatility_task_handles_adjustment_warning_and_per_portfolio_error(monkeypatch) -> None:
    """Volatility processing keeps its existing per-portfolio outcome contract."""

    portfolios = [
        {"id": 1, "user_id": 10},
        {"id": 2, "user_id": 20},
        {"id": 3, "user_id": 30},
    ]
    monkeypatch.setattr(
        tasks.portfolio_repo,
        "list_active_portfolios",
        lambda user_id=None: portfolios,
    )
    analyses = {
        1: SimpleNamespace(
            adjustment_result=SimpleNamespace(should_reduce=True, volatility_ratio=1.5)
        ),
        2: SimpleNamespace(
            adjustment_result=SimpleNamespace(should_reduce=False, volatility_ratio=1.1)
        ),
    }

    def _analyze(*, portfolio_id: int, user_id: int) -> object:
        del user_id
        if portfolio_id == 3:
            raise RuntimeError("broken portfolio")
        return analyses[portfolio_id]

    monkeypatch.setattr(
        tasks,
        "VolatilityAnalysisUseCase",
        lambda: SimpleNamespace(analyze_portfolio_volatility=_analyze),
    )
    monkeypatch.setattr(
        tasks,
        "VolatilityAdjustmentUseCase",
        lambda: SimpleNamespace(
            execute_volatility_adjustment=lambda **kwargs: {"status": "executed"}
        ),
    )
    monkeypatch.setattr(tasks, "_send_volatility_adjustment_notification", lambda **kwargs: None)
    monkeypatch.setattr(tasks, "_send_volatility_warning_notification", lambda **kwargs: None)
    result = tasks.check_volatility_and_adjust_task.run()
    assert result["status"] == "success"
    assert result["checked_count"] == 3
    assert result["adjusted_count"] == 1
    assert result["warning_count"] == 1
