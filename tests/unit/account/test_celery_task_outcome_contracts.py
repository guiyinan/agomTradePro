from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.account.application import tasks
from apps.task_monitor.application.dtos import project_task_business_result
from apps.task_monitor.application.tasks import _serialize_task_result


def _exit_result(
    *,
    triggered: bool = False,
    check_status: str = "evaluated",
    execution_status: str = "not_triggered",
    receipt_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        position_id=1,
        asset_code="000001.SZ",
        triggered=triggered,
        check_status=check_status,
        execution_status=execution_status,
        reason_code=(
            "legacy_automatic_exit_not_qualified" if execution_status == "blocked" else None
        ),
        check_result=None,
        current_price=10.0 if check_status == "evaluated" else None,
        price_source="unified_quote" if check_status == "evaluated" else None,
        price_observed_at=datetime(2026, 4, 1, tzinfo=UTC) if check_status == "evaluated" else None,
        price_freshness="realtime" if check_status == "evaluated" else None,
        must_not_use_for_decision=True,
        must_not_execute=True,
        unrealized_pnl=None,
        unrealized_pnl_pct=None,
        partial_level=None,
        execution_receipt_id=receipt_id,
    )


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


def test_backup_task_registration_and_delay_contract(monkeypatch) -> None:
    """The backup function remains a registered Celery task with a working delay path."""

    task = tasks.send_database_backup_email_task
    assert task.name == "apps.account.application.tasks.send_database_backup_email_task"
    assert task.name in task.app.tasks
    captured: dict[str, object] = {}

    def _apply_async(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "queued"

    monkeypatch.setattr(task, "apply_async", _apply_async)
    assert task.delay() == "queued"
    assert captured["args"] == ((), {})
    assert captured["kwargs"] == {}


def test_stop_loss_and_take_profit_publish_trigger_and_check_counts(monkeypatch) -> None:
    """A trigger is blocked intent; only a valid check counts as succeeded."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [
                _exit_result(triggered=True, execution_status="blocked"),
                _exit_result(),
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

    assert stop_loss["outcome"] == "partial"
    assert (stop_loss["requested"], stop_loss["succeeded"], stop_loss["failed"]) == (2, 1, 1)
    assert stop_loss["triggered_count"] == 1
    assert stop_loss["blocked_count"] == 1
    assert stop_loss["executed_count"] == 0
    assert stop_loss["stored"] == 0
    assert take_profit["outcome"] == "noop"
    assert take_profit["success"] is True
    assert take_profit["requested"] == take_profit["stored"] == 0


def test_no_trigger_checks_are_success_without_execution_or_storage(monkeypatch) -> None:
    """A valid no-trigger observation succeeds while execution and storage stay zero."""

    no_trigger = [_exit_result()]
    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(check_and_execute_stop_loss=lambda **_kwargs: no_trigger),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(check_and_execute_take_profit=lambda **_kwargs: no_trigger),
    )

    results = (
        tasks.check_stop_loss_task.run(user_id=7),
        tasks.check_take_profit_task.run(user_id=7),
        tasks.check_stop_loss_and_take_profit_task.run(user_id=7),
    )

    for result in results:
        assert result["outcome"] == "success"
        assert result["requested"] == result["succeeded"]
        assert result["failed"] == 0
        assert result["executed_count"] == 0
        assert result["stored"] == 0


def test_blocked_and_unavailable_checks_are_distinguished(monkeypatch) -> None:
    """Trigger blocks and unavailable prices remain separate outcome counts."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [
                _exit_result(triggered=True, execution_status="blocked"),
                _exit_result(check_status="unavailable"),
            ]
        ),
    )
    monkeypatch.setattr(tasks, "_send_stop_loss_notifications", lambda *_args: None)

    result = tasks.check_stop_loss_task.run(user_id=7)

    assert result["outcome"] == "failed"
    assert result["requested"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["triggered_count"] == 1
    assert result["blocked_count"] == 1
    assert result["check_unavailable_count"] == 1
    assert result["stored"] == 0


def test_fully_triggered_legacy_exits_are_blocked_for_all_three_tasks(monkeypatch) -> None:
    """Each compatibility task exposes blocked intent with zero confirmed receipts."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [
                _exit_result(triggered=True, execution_status="blocked")
            ]
        ),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(
            check_and_execute_take_profit=lambda **_kwargs: [
                _exit_result(triggered=True, execution_status="blocked")
            ]
        ),
    )
    monkeypatch.setattr(tasks, "_send_stop_loss_notifications", lambda *_args: None)
    monkeypatch.setattr(tasks, "_send_take_profit_notifications", lambda *_args: None)

    stop = tasks.check_stop_loss_task.run(user_id=7)
    take = tasks.check_take_profit_task.run(user_id=7)
    combined = tasks.check_stop_loss_and_take_profit_task.run(user_id=7)

    for result in (stop, take, combined):
        assert result["outcome"] == "blocked"
        assert result["triggered_count"] >= 1
        assert result["blocked_count"] >= 1
        assert result["executed_count"] == 0
        assert result["stored"] == 0


def test_unknown_execution_never_becomes_zero_stored(monkeypatch) -> None:
    """Unknown execution status preserves unknown storage counts and is observable."""

    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(
            check_and_execute_take_profit=lambda **_kwargs: [
                _exit_result(
                    triggered=True,
                    execution_status="unknown",
                )
            ]
        ),
    )
    monkeypatch.setattr(tasks, "_send_take_profit_notifications", lambda *_args: None)

    result = tasks.check_take_profit_task.run(user_id=7)

    assert result["outcome"] == "failed"
    assert result["execution_unknown_count"] == 1
    assert result["counts_unavailable"] is True
    assert result["stored"] is None


def test_unverified_confirmed_receipt_remains_unknown_and_unstored(monkeypatch) -> None:
    """A non-empty caller-supplied receipt id is not authoritative settlement proof."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [
                _exit_result(
                    triggered=True,
                    execution_status="confirmed",
                    receipt_id="unverified-receipt",
                )
            ]
        ),
    )

    result = tasks.check_stop_loss_task.run(user_id=7)

    assert result["executed_count"] == 0
    assert result["execution_unknown_count"] == 1
    assert result["stored"] is None


def test_notifications_do_not_lookup_missing_position_identity(monkeypatch) -> None:
    """Unknown identity is rejected before owner/contact lookup or email."""

    def _must_not_lookup(_position_id):
        raise AssertionError("missing position identity reached the repository")

    monkeypatch.setattr(tasks.position_repo, "get_position_notification_context", _must_not_lookup)
    monkeypatch.setattr(
        tasks,
        "send_mail",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("email must not be sent")),
    )
    result = SimpleNamespace(
        triggered=True,
        position_id=None,
        asset_code=None,
        check_result=SimpleNamespace(trigger_reason="risk threshold"),
        current_price=10.0,
        unrealized_pnl_pct=-0.1,
        partial_level=None,
    )

    tasks._send_stop_loss_notifications([result], user_id=7)
    tasks._send_take_profit_notifications([result], user_id=7)


@pytest.mark.parametrize("owner_id", [0, -1, True])
def test_notifications_reject_invalid_owner_before_email(monkeypatch, owner_id) -> None:
    """A global scan still requires an exact positive owner id before mail delivery."""

    result = _exit_result(triggered=True, execution_status="blocked")
    result.check_result = SimpleNamespace(trigger_reason="阈值")
    result.unrealized_pnl_pct = -0.1
    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda _position_id: {"user_id": owner_id, "user_email": "owner@example.test"},
    )
    monkeypatch.setattr(
        tasks,
        "send_mail",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("invalid owner reached email")),
    )

    tasks._send_stop_loss_notifications([result], user_id=None)


def test_notice_failure_is_logged_without_changing_exit_outcome(monkeypatch, caplog) -> None:
    """Mail failure stays diagnostic and cannot become a stored or executed result."""

    result = _exit_result(triggered=True, execution_status="blocked")
    result.check_result = SimpleNamespace(trigger_reason="当前价低于止损阈值")
    result.unrealized_pnl_pct = -0.1
    result.price_source = "unified_quote"
    result.price_observed_at = datetime(2026, 4, 1, tzinfo=UTC)
    result.price_freshness = "realtime"
    notices: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks.position_repo,
        "get_position_notification_context",
        lambda _position_id: {"user_id": 7, "user_email": "owner@example.test"},
    )

    def _fail_notice(**kwargs):
        notices.append(kwargs)
        raise RuntimeError("mail transport unavailable")

    monkeypatch.setattr(tasks, "send_mail", _fail_notice)
    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(check_and_execute_stop_loss=lambda **_kwargs: [result]),
    )

    outcome = tasks.check_stop_loss_task.run(user_id=7)

    assert len(notices) == 1
    assert "价格观察: 10.00" in notices[0]["message"]
    assert "源观测时间: 2026-04-01T00:00:00+00:00" in notices[0]["message"]
    assert "当前价" not in notices[0]["message"]
    assert "成交" not in notices[0]["subject"]
    assert "reason_code=notification_delivery_failed" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "mail transport unavailable" not in caplog.text
    assert outcome["outcome"] == "blocked"
    assert outcome["executed_count"] == 0
    assert outcome["stored"] == 0


def test_invalid_user_is_rejected_before_use_case_construction(monkeypatch) -> None:
    """Boolean ids are rejected for standalone and combined tasks before repositories."""

    def _must_not_construct():
        raise AssertionError("use case construction must not run")

    monkeypatch.setattr(tasks, "AutoStopLossUseCase", _must_not_construct)
    monkeypatch.setattr(tasks, "AutoTakeProfitUseCase", _must_not_construct)
    results = [
        tasks.check_stop_loss_task.run(user_id=True),
        tasks.check_take_profit_task.run(user_id=True),
        tasks.check_stop_loss_and_take_profit_task.run(user_id=True),
    ]

    assert all(result["outcome"] == "failed" for result in results)
    assert all(result["reason_code"] == "invalid_user_id" for result in results)
    assert all(result["count_unit"] == "task_invocation" for result in results)
    assert all(result["checked_count"] is None for result in results)
    assert all(result["stored"] == 0 for result in results)


def test_exception_after_stage_entry_is_unknown_and_not_retried(monkeypatch) -> None:
    """An entered check stage is never retried after its write outcome can be unclear."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("provider unavailable")
            )
        ),
    )
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_stop_loss_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stage must not retry")),
    )

    result = tasks.check_stop_loss_task.run(user_id=7)

    assert result["outcome"] == "failed"
    assert result["stage_unknown_count"] == 1
    assert result["counts_unavailable"] is True
    assert result["requested"] is None
    assert result["stored"] is None


def test_take_profit_stage_exception_is_unknown_and_not_retried(monkeypatch) -> None:
    """A take-profit stage error after entry remains unknown and is not replayed."""

    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(
            check_and_execute_take_profit=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("provider unavailable")
            )
        ),
    )
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_take_profit_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stage must not retry")),
    )

    result = tasks.check_take_profit_task.run(user_id=7)

    assert result["outcome"] == "failed"
    assert result["stage_unknown_count"] == 1
    assert result["counts_unavailable"] is True
    assert result["requested"] is None
    assert result["stored"] is None


def test_combined_task_preserves_diagnostic_stage_snapshots(monkeypatch) -> None:
    """Combined results retain counts without publishing replayable checkpoints."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: [
                _exit_result(triggered=True, execution_status="blocked")
            ]
        ),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(check_and_execute_take_profit=lambda **_kwargs: [_exit_result()]),
    )
    monkeypatch.setattr(tasks, "_send_stop_loss_notifications", lambda *_args: None)

    result = tasks.check_stop_loss_and_take_profit_task.run(user_id=7)

    assert result["outcome"] == "partial"
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["stop_loss_checked"] == 1
    assert result["stop_loss_triggered"] == 1
    assert result["stop_loss_executed"] == 0
    assert result["stop_loss_blocked"] == 1
    assert result["take_profit_checked"] == 1
    snapshots = result["stage_snapshots"]
    assert set(snapshots) == {"stop_loss", "take_profit"}
    assert snapshots["stop_loss"]["completed"] is True
    assert snapshots["stop_loss"]["stored"] == 0
    assert snapshots["take_profit"]["succeeded"] == 1
    assert "checkpoint" not in result


def test_combined_unknown_stop_stage_stops_without_retry_or_take_profit(monkeypatch) -> None:
    """An unknown first stage cannot be retried or followed by another stage."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(
            check_and_execute_stop_loss=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("stage state unknown")
            )
        ),
    )
    take_case = SimpleNamespace(
        check_and_execute_take_profit=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("take-profit stage must not enter")
        )
    )
    monkeypatch.setattr(tasks, "AutoTakeProfitUseCase", lambda: take_case)
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_stop_loss_and_take_profit_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unknown stage must not retry")),
    )

    result = tasks.check_stop_loss_and_take_profit_task.run(user_id=7)

    assert result["outcome"] == "failed"
    assert result["stage_unknown_count"] == 1
    assert result["counts_unavailable"] is True
    assert result["stored"] is None
    assert result["take_profit_checked"] is None
    assert result["stage_snapshots"]["take_profit"] is None


def test_combined_unknown_take_stage_preserves_stop_counts_and_stops_without_retry(
    monkeypatch,
) -> None:
    """A second-stage unknown retains known checks but makes the aggregate partial."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: SimpleNamespace(check_and_execute_stop_loss=lambda **_kwargs: [_exit_result()]),
    )
    monkeypatch.setattr(
        tasks,
        "AutoTakeProfitUseCase",
        lambda: SimpleNamespace(
            check_and_execute_take_profit=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("take stage state unknown")
            )
        ),
    )
    monkeypatch.setattr(tasks, "record_exception", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks.check_stop_loss_and_take_profit_task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unknown stage must not retry")),
    )

    result = tasks.check_stop_loss_and_take_profit_task.run(user_id=7)
    projection = project_task_business_result(_serialize_task_result(result))

    assert result["status"] == "error"
    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["requested"] is None
    assert result["succeeded"] is None
    assert result["failed"] is None
    assert result["stop_loss_checked"] == 1
    assert result["take_profit_checked"] is None
    assert result["stage_unknown_count"] == 1
    assert result["counts_unavailable"] is True
    assert result["stored"] is None
    assert result["executed_count"] == 0
    assert result["stop_loss_executed"] == 0
    assert result["take_profit_executed"] == 0
    assert result["stage_snapshots"]["stop_loss"]["outcome"] == "success"
    assert (
        result["stage_snapshots"]["stop_loss"]["requested"],
        result["stage_snapshots"]["stop_loss"]["succeeded"],
        result["stage_snapshots"]["stop_loss"]["failed"],
        result["stage_snapshots"]["stop_loss"]["stored"],
    ) == (1, 1, 0, 0)
    assert result["stage_snapshots"]["stop_loss"]["executed_count"] == 0
    assert result["stage_snapshots"]["take_profit"]["stage_unknown_count"] == 1
    assert result["stage_snapshots"]["take_profit"]["counts_unavailable"] is True
    assert projection.outcome == "partial"
    assert projection.business_success is False
    assert projection.counts_unavailable is True
    assert (projection.requested, projection.succeeded, projection.failed, projection.stored) == (
        None,
        None,
        None,
        None,
    )
    assert projection.stored_count_unit == "confirmed_simulated_trade_receipt"
    assert "checkpoint" not in result


@pytest.mark.parametrize(
    "checkpoint",
    [
        {"stop_loss": {"outcome": "noop", "requested": 0, "stored": 0}},
        {"owner_id": 999, "stop_loss": {"outcome": "success", "stored": 1}},
    ],
)
def test_nonempty_or_cross_owner_checkpoint_is_rejected_before_construction(
    monkeypatch,
    checkpoint,
) -> None:
    """Diagnostic or cross-owner snapshots cannot authorize stage replay."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: (_ for _ in ()).throw(AssertionError("invalid checkpoint reached repository")),
    )
    result = tasks.check_stop_loss_and_take_profit_task.run(
        user_id=7,
        checkpoint=checkpoint,
    )

    assert result["outcome"] == "failed"
    assert result["reason_code"] == "invalid_checkpoint"
    assert result["checked_count"] is None
    assert result["stored"] == 0


def test_forged_nonempty_receipt_checkpoint_is_rejected(monkeypatch) -> None:
    """Caller-supplied execution counts never authorize re-entry or stored counts."""

    monkeypatch.setattr(
        tasks,
        "AutoStopLossUseCase",
        lambda: (_ for _ in ()).throw(AssertionError("forged checkpoint reached stage")),
    )
    checkpoint = {
        "stop_loss": {
            "completed": True,
            "outcome": "success",
            "requested": 1,
            "succeeded": 1,
            "failed": 0,
            "triggered_count": 1,
            "executed_count": 1,
            "blocked_count": 0,
            "check_unavailable_count": 0,
            "execution_unknown_count": 0,
            "stage_unknown_count": 0,
            "stored": 1,
            "counts_unavailable": False,
        }
    }

    result = tasks.check_stop_loss_and_take_profit_task.run(user_id=7, checkpoint=checkpoint)

    assert result["outcome"] == "failed"
    assert result["reason_code"] == "invalid_checkpoint"
    assert result["executed_count"] == 0
    assert result["stored"] == 0


def test_combined_setup_retry_has_no_stage_or_notification_side_effects(monkeypatch) -> None:
    """Both use cases are built before stage entry; setup retry carries no checkpoint."""

    calls: list[str] = []
    captured: dict[str, object] = {}

    class _StopCase:
        def check_and_execute_stop_loss(self, **_kwargs):
            calls.append("stop_stage")
            return [_exit_result(triggered=True, execution_status="blocked")]

    def _stop_setup():
        calls.append("stop_setup")
        return _StopCase()

    def _take_setup():
        calls.append("take_setup")
        raise RuntimeError("setup unavailable")

    def _retry(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("retry scheduled")

    monkeypatch.setattr(tasks, "AutoStopLossUseCase", _stop_setup)
    monkeypatch.setattr(tasks, "AutoTakeProfitUseCase", _take_setup)
    monkeypatch.setattr(tasks.check_stop_loss_and_take_profit_task, "retry", _retry)
    monkeypatch.setattr(
        tasks,
        "_send_stop_loss_notifications",
        lambda *_args: calls.append("notice"),
    )

    with pytest.raises(RuntimeError, match="retry scheduled"):
        tasks.check_stop_loss_and_take_profit_task.run(user_id=7)

    assert calls == ["stop_setup", "take_setup"]
    assert captured["kwargs"] == {"user_id": 7, "checkpoint": None}


def test_volatility_task_reports_partial_and_complete_failure(monkeypatch) -> None:
    """Per-portfolio errors contribute to partial/failed instead of being hidden."""

    portfolios = [{"id": 1, "user_id": 10}, {"id": 2, "user_id": 20}]
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
