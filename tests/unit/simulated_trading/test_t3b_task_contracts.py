"""T3B simulated-trading task contracts for performance and maintenance outcomes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import tasks


def test_task_runtime_helpers_validate_identifiers_and_delegate_price_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dynamic task payload IDs are strict and realtime polling stays in its owner app."""
    assert tasks._require_int_field({"account_id": 7}, "account_id") == 7
    with pytest.raises(ValueError, match="must be an integer"):
        tasks._require_int_field({"account_id": True}, "account_id")

    monkeypatch.setattr(
        tasks,
        "PricePollingUseCase",
        lambda: SimpleNamespace(execute_price_polling=lambda: {"status": "success", "updated": 2}),
    )
    assert tasks.execute_realtime_price_polling() == {
        "status": "success",
        "updated": 2,
    }


def test_performance_task_isolates_account_failure_and_serializes_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed account does not erase successful performance evidence."""
    accounts = [
        SimpleNamespace(account_id=1, account_name="one"),
        SimpleNamespace(account_id=2, account_name="two"),
    ]

    class _Calculator:
        def calculate_and_update_performance(
            self,
            *,
            account_id: int,
            trade_date,
        ) -> dict[str, float]:
            if account_id == 2:
                raise RuntimeError("account history malformed")
            return {
                "total_return": 0.12,
                "sharpe_ratio": 1.3,
                "max_drawdown": 0.08,
                "win_rate": 0.6,
            }

    monkeypatch.setattr(tasks, "PerformanceCalculator", _Calculator)
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        lambda: SimpleNamespace(get_active_accounts=lambda: accounts),
    )
    result = tasks.calculate_all_performance_task.run("2026-07-24")
    assert result["success"] is True
    assert result["account_count"] == 1
    assert result["results"] == [
        {
            "account_id": 1,
            "account_name": "one",
            "total_return": 0.12,
            "sharpe_ratio": 1.3,
            "max_drawdown": 0.08,
            "win_rate": 0.6,
        }
    ]


def test_performance_task_reports_repository_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure before account iteration cannot be reported as an empty successful run."""
    monkeypatch.setattr(
        tasks,
        "PerformanceCalculator",
        lambda: (_ for _ in ()).throw(RuntimeError("calculator unavailable")),
    )
    result = tasks.calculate_all_performance_task.run("2026-07-24")
    assert result == {
        "outcome": "failed",
        "success": False,
        "requested": 1,
        "succeeded": 0,
        "failed": 1,
        "stored": 0,
        "error": "calculator unavailable",
    }


def test_performance_summary_filters_requested_accounts_and_records_delivery(
    monkeypatch: pytest.MonkeyPatch,
    settings,
) -> None:
    """Summary task skips unknown account IDs and records per-recipient delivery."""
    accounts = {
        1: SimpleNamespace(account_id=1, account_name="one", total_value=1000),
        2: SimpleNamespace(account_id=2, account_name="two", total_value=2000),
    }
    account_repo = SimpleNamespace(get_by_id=lambda account_id: accounts.get(account_id))
    position_repo = SimpleNamespace()
    trade_repo = SimpleNamespace()
    monkeypatch.setattr(tasks, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(tasks, "get_simulated_position_repository", lambda: position_repo)
    monkeypatch.setattr(tasks, "get_simulated_trade_repository", lambda: trade_repo)

    class _PerformanceUseCase:
        def __init__(self, *args: object) -> None:
            assert args == (account_repo, position_repo, trade_repo)

        def execute(self, account_id: int) -> dict[str, object]:
            return {
                "performance": {
                    "total_return": 0.1,
                    "max_drawdown": 0.05,
                    "sharpe_ratio": 1.2,
                    "win_rate": 0.6,
                },
                "total_trades": account_id + 2,
                "total_positions": account_id,
            }

    monkeypatch.setattr(tasks, "GetAccountPerformanceUseCase", _PerformanceUseCase)
    settings.PERFORMANCE_SUMMARY_RECIPIENTS = [
        "owner@example.test",
        "ops@example.test",
    ]
    from shared.infrastructure import notification_service as notification_module

    delivery_results = [
        SimpleNamespace(
            recipient=SimpleNamespace(email="owner@example.test"),
            success=True,
        ),
        SimpleNamespace(
            recipient=SimpleNamespace(email="ops@example.test"),
            success=False,
        ),
    ]
    sent: dict[str, object] = {}

    def _send_email(**kwargs: object) -> list[SimpleNamespace]:
        sent.update(kwargs)
        return delivery_results

    monkeypatch.setattr(
        notification_module,
        "get_notification_service",
        lambda: SimpleNamespace(send_email=_send_email),
    )
    result = tasks.send_performance_summary_task.run(account_ids=[1, 99, 2])
    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        3,
        2,
        1,
        0,
    )
    assert (
        result["requested_recipient_count"],
        result["succeeded_recipient_count"],
        result["failed_recipient_count"],
    ) == (2, 1, 1)
    assert len(result["summaries"]) == 2
    assert result["notifications"] == [
        {"email": "owner@example.test", "success": True},
        {"email": "ops@example.test", "success": False},
    ]
    assert "账户: one" in str(sent["body"])
    assert sent["recipients"] == settings.PERFORMANCE_SUMMARY_RECIPIENTS


def test_performance_summary_notification_and_repository_failures_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
    settings,
) -> None:
    """Notification failure is non-fatal while account repository failure is fatal."""
    account = SimpleNamespace(account_id=1, account_name="one", total_value=1000)
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        lambda: SimpleNamespace(get_active_accounts=lambda: [account]),
    )
    monkeypatch.setattr(tasks, "get_simulated_position_repository", lambda: SimpleNamespace())
    monkeypatch.setattr(tasks, "get_simulated_trade_repository", lambda: SimpleNamespace())
    monkeypatch.setattr(
        tasks,
        "GetAccountPerformanceUseCase",
        lambda *args: SimpleNamespace(
            execute=lambda account_id: {
                "performance": {},
                "total_trades": 0,
                "total_positions": 0,
            }
        ),
    )
    settings.PERFORMANCE_SUMMARY_RECIPIENTS = ["owner@example.test"]
    from shared.infrastructure import notification_service as notification_module

    monkeypatch.setattr(
        notification_module,
        "get_notification_service",
        lambda: (_ for _ in ()).throw(RuntimeError("mail transport offline")),
    )
    result = tasks.send_performance_summary_task.run()
    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["notification_error"] == "mail transport offline"
    assert result["notifications"] == []

    settings.PERFORMANCE_SUMMARY_RECIPIENTS = []
    monkeypatch.setattr(
        notification_module,
        "get_notification_service",
        lambda: (_ for _ in ()).throw(AssertionError("unused notification dependency")),
    )
    no_delivery = tasks.send_performance_summary_task.run()
    assert no_delivery["outcome"] == "success"
    assert no_delivery["notification_error"] is None

    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        lambda: (_ for _ in ()).throw(RuntimeError("account DB offline")),
    )
    assert tasks.send_performance_summary_task.run() == {
        "outcome": "failed",
        "success": False,
        "requested": 1,
        "succeeded": 0,
        "failed": 1,
        "stored": 0,
        "error": "account DB offline",
    }
