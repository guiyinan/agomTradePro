"""Normalized business-outcome contracts for Account Celery tasks."""

from __future__ import annotations

from types import SimpleNamespace

from apps.account.application import tasks
from core.exceptions import BusinessLogicError


def _position_result(*, should_close: bool) -> SimpleNamespace:
    return SimpleNamespace(should_close=should_close)


def test_backup_delivery_reports_noop_and_success_counts(monkeypatch) -> None:
    """A non-due delivery is noop while a sent delivery is one stored success."""
    config = SimpleNamespace(
        is_backup_due=lambda: False,
        backup_interval_days=7,
        backup_link_ttl_days=2,
        backup_password_hint="hint",
        backup_mail_from_email="from@example.test",
        backup_email="owner@example.test",
        pk=1,
    )
    monkeypatch.setattr(tasks.system_settings_repo, "get_settings", lambda: config)

    skipped = tasks.send_database_backup_email_task.run()
    assert {
        key: skipped[key]
        for key in ("outcome", "success", "requested", "succeeded", "failed", "stored")
    } == {
        "outcome": "noop",
        "success": True,
        "requested": 1,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
    }

    config.is_backup_due = lambda: True
    monkeypatch.setattr(tasks, "generate_download_token", lambda _config: "token")
    monkeypatch.setattr(tasks, "build_backup_download_url", lambda _token: "https://backup")
    monkeypatch.setattr(
        tasks,
        "describe_backup_package",
        lambda: {"extension": ".zip", "format": "encrypted"},
    )
    monkeypatch.setattr(tasks, "get_backup_email_connection", lambda _config: object())
    monkeypatch.setattr(
        tasks,
        "EmailMessage",
        lambda **_kwargs: SimpleNamespace(send=lambda **_send_kwargs: 1),
    )
    monkeypatch.setattr(tasks, "mark_backup_delivery_sent", lambda _sent_at: None)

    sent = tasks.send_database_backup_email_task.run()
    assert {
        key: sent[key]
        for key in ("outcome", "success", "requested", "succeeded", "failed", "stored")
    } == {
        "outcome": "success",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 1,
    }


def test_stop_loss_and_take_profit_publish_success_and_noop(monkeypatch) -> None:
    """Independent risk checks publish counts using the same normalized vocabulary."""
    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [
                _position_result(should_close=True),
                _position_result(should_close=False),
            ]
        ),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(check_and_execute_take_profit=lambda **_kwargs: []),
    )
    monkeypatch.setattr(tasks, "_send_stop_loss_notifications", lambda *_args: None)

    stop_loss = tasks.check_stop_loss_task.run(user_id=7)
    take_profit = tasks.check_take_profit_task.run(user_id=7)

    assert stop_loss["outcome"] == "success"
    assert stop_loss["requested"] == stop_loss["succeeded"] == 2
    assert stop_loss["failed"] == 0
    assert stop_loss["stored"] == 1
    assert take_profit["outcome"] == "noop"
    assert take_profit["success"] is True
    assert take_profit["requested"] == take_profit["stored"] == 0


def test_stop_loss_business_failure_has_failed_outcome(monkeypatch) -> None:
    """A non-retryable business rejection must not look like a successful task."""

    def _fail(**_kwargs):
        raise BusinessLogicError("invalid risk rule")

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(check_and_execute_stop_loss=_fail),
    )
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)

    result = tasks.check_stop_loss_task.run(user_id=7)

    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["requested"] == result["succeeded"] == result["stored"] == 0
    assert result["failed"] == 1


def test_combined_risk_check_publishes_aggregate_counts(monkeypatch) -> None:
    """The combined task reports the two completed stages as one coherent result."""
    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [_position_result(should_close=True)]
        ),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(
            check_and_execute_take_profit=lambda **_kwargs: [_position_result(should_close=False)]
        ),
    )
    monkeypatch.setattr(tasks, "_send_stop_loss_notifications", lambda *_args: None)

    result = tasks.check_stop_loss_and_take_profit_task.run(user_id=7)

    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["stored"] == 1


def test_volatility_task_reports_partial_and_complete_failure(monkeypatch) -> None:
    """Per-portfolio errors contribute to partial/failed instead of being hidden."""
    portfolios = [
        {"id": 1, "user_id": 10},
        {"id": 2, "user_id": 20},
    ]
    monkeypatch.setattr(
        tasks.portfolio_repo,
        "list_active_portfolios",
        lambda **_kwargs: portfolios,
    )

    def _partially_fail(*, portfolio_id: int, user_id: int) -> SimpleNamespace:
        del user_id
        if portfolio_id == 2:
            raise RuntimeError("source unavailable")
        return SimpleNamespace(
            adjustment_result=SimpleNamespace(should_reduce=False, volatility_ratio=0.5)
        )

    monkeypatch.setattr(
        tasks,
        "VolatilityAnalysisUseCase",
        lambda: SimpleNamespace(analyze_portfolio_volatility=_partially_fail),
    )
    partial = tasks.check_volatility_and_adjust_task.run(user_id=7)
    assert partial["outcome"] == "partial"
    assert partial["success"] is True
    assert (partial["requested"], partial["succeeded"], partial["failed"]) == (2, 1, 1)

    monkeypatch.setattr(
        tasks,
        "VolatilityAnalysisUseCase",
        lambda: SimpleNamespace(
            analyze_portfolio_volatility=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("source unavailable")
            )
        ),
    )
    failed = tasks.check_volatility_and_adjust_task.run(user_id=7)
    assert failed["outcome"] == "failed"
    assert failed["success"] is False
    assert (failed["requested"], failed["succeeded"], failed["failed"]) == (2, 0, 2)
