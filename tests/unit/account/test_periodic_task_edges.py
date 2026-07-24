"""Account periodic-task result and notification contracts."""

from __future__ import annotations

from types import SimpleNamespace

from apps.account.application import tasks


def _result(*, should_close: bool = True, partial_level: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        should_close=should_close,
        asset_code="000001.SZ",
        position_id=1,
        current_price=10.5,
        unrealized_pnl_pct=-0.1,
        partial_level=partial_level,
        check_result=SimpleNamespace(trigger_reason="risk threshold", stop_price=10.0),
    )


def test_stop_loss_take_profit_and_combined_tasks_report_counts(monkeypatch) -> None:
    """Periodic checks report checked/triggered counts and invoke notifications."""
    stop_results = [_result(), _result(should_close=False)]
    take_results = [_result(partial_level="L1")]
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
    notifications: list[tuple[str, int]] = []
    monkeypatch.setattr(
        tasks,
        "_send_stop_loss_notifications",
        lambda results, user_id=None: notifications.append(("stop", len(results))),
    )
    monkeypatch.setattr(
        tasks,
        "_send_take_profit_notifications",
        lambda results, user_id=None: notifications.append(("take", len(results))),
    )

    stop = tasks.check_stop_loss_task.run(user_id=1)
    take = tasks.check_take_profit_task.run(user_id=1)
    combined = tasks.check_stop_loss_and_take_profit_task.run(user_id=1)
    assert stop == {"status": "success", "checked_count": 2, "triggered_count": 1}
    assert take == {"status": "success", "checked_count": 1, "triggered_count": 1}
    assert combined["stop_loss_triggered"] == 1
    assert combined["take_profit_triggered"] == 1
    assert ("stop", 1) in notifications and ("take", 1) in notifications


def test_notification_helpers_send_only_when_owner_email_exists(monkeypatch) -> None:
    """Notification helpers look up the owning email and tolerate missing recipients."""
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda position_id: {"user_email": "owner@example.test"},
    )
    monkeypatch.setattr(tasks, "send_mail", lambda **kwargs: sent.append(kwargs))
    tasks._send_stop_loss_notifications([_result()])
    tasks._send_take_profit_notifications([_result(partial_level="L1")])
    assert len(sent) == 2
    assert sent[0]["recipient_list"] == ["owner@example.test"]
    assert "分批 L1" in sent[1]["message"]

    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda position_id: None,
    )
    tasks._send_stop_loss_notifications([_result()])
    assert len(sent) == 2


def test_volatility_task_handles_adjustment_warning_and_per_portfolio_error(monkeypatch) -> None:
    """Volatility processing isolates one portfolio and counts adjustment/warning outcomes."""
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
