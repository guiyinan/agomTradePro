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
        1: SimpleNamespace(
            account_id=1,
            account_name="one",
            total_value=1000,
            cash_known=True,
        ),
        2: SimpleNamespace(
            account_id=2,
            account_name="cash-unknown",
            total_value=2000,
            cash_known=False,
        ),
        3: SimpleNamespace(
            account_id=3,
            account_name="valuation-unknown",
            total_value=3000,
            cash_known=True,
        ),
        4: SimpleNamespace(
            account_id=4,
            account_name="cost-unknown",
            total_value=4000,
            cash_known=True,
        ),
    }
    account_repo = SimpleNamespace(get_by_id=lambda account_id: accounts.get(account_id))
    positions = {
        1: [SimpleNamespace(valuation_known=True)],
        2: [SimpleNamespace(valuation_known=True)],
        3: [SimpleNamespace(valuation_known=False)],
        4: [SimpleNamespace(valuation_known=True)],
    }
    position_repo = SimpleNamespace(get_by_account=lambda account_id: positions[account_id])
    trade_repo = SimpleNamespace()
    monkeypatch.setattr(tasks, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(tasks, "get_simulated_position_repository", lambda: position_repo)
    monkeypatch.setattr(tasks, "get_simulated_trade_repository", lambda: trade_repo)

    class _PerformanceUseCase:
        def __init__(self, *args: object) -> None:
            assert args == (account_repo, position_repo, trade_repo)

        def execute(self, account_id: int) -> dict[str, object]:
            metrics = {
                1: {
                    "total_return": 10.0,
                    "annual_return": 12.0,
                    "max_drawdown": 5.0,
                    "sharpe_ratio": 1.2,
                    "win_rate": 50.0,
                },
                2: {
                    "total_return": 20.0,
                    "annual_return": 22.0,
                    "max_drawdown": 15.0,
                    "sharpe_ratio": 2.4,
                    "win_rate": None,
                },
                3: {
                    "total_return": 30.0,
                    "annual_return": 32.0,
                    "max_drawdown": 25.0,
                    "sharpe_ratio": 3.6,
                    "win_rate": 40.0,
                },
                4: {
                    "total_return": None,
                    "annual_return": None,
                    "max_drawdown": None,
                    "sharpe_ratio": None,
                    "win_rate": None,
                },
            }
            return {
                "account": accounts[account_id],
                "positions": positions[account_id],
                "performance": metrics[account_id],
                "total_trades": account_id + 2,
                "total_positions": account_id,
                "win_rate_known": account_id in (1, 3),
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
    result = tasks.send_performance_summary_task.run(account_ids=[1, 99, 2, 3, 4])
    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert (
        result["requested"],
        result["succeeded"],
        result["failed"],
        result["stored"],
    ) == (
        5,
        4,
        1,
        0,
    )
    assert (
        result["requested_recipient_count"],
        result["succeeded_recipient_count"],
        result["failed_recipient_count"],
    ) == (2, 1, 1)
    assert len(result["summaries"]) == 4
    assert result["notifications"] == [
        {"email": "owner@example.test", "success": True},
        {"email": "ops@example.test", "success": False},
    ]
    body = str(sent["body"])
    assert (
        "\n账户: one\n  总资产: 1,000.00\n  总收益: 10.00%\n  最大回撤: 5.00%"
        "\n  夏普比率: 1.20\n  胜率: 50.00%"
    ) in body
    cash_unknown_section = body.split("\n账户: cash-unknown\n", 1)[1].split(
        "\n账户: valuation-unknown\n", 1
    )[0]
    assert "总资产: 未知（现金或持仓估值不完整）" in cash_unknown_section
    assert "总收益: 未知（现金或持仓估值不完整）" in cash_unknown_section
    assert "最大回撤: 未知（现金或持仓估值不完整）" in cash_unknown_section
    assert "夏普比率: 未知（现金或持仓估值不完整）" in cash_unknown_section
    assert "胜率: 未知" in cash_unknown_section
    assert "2,000.00" not in cash_unknown_section
    valuation_unknown_section = body.rsplit("\n账户: valuation-unknown\n", 1)[1]
    assert "总资产: 未知（现金或持仓估值不完整）" in valuation_unknown_section
    assert "总收益: 未知（现金或持仓估值不完整）" in valuation_unknown_section
    assert "最大回撤: 未知（现金或持仓估值不完整）" in valuation_unknown_section
    assert "夏普比率: 未知（现金或持仓估值不完整）" in valuation_unknown_section
    assert "胜率: 40.00%" in valuation_unknown_section
    assert "3,000.00" not in valuation_unknown_section
    cost_unknown_section = body.rsplit("\n账户: cost-unknown\n", 1)[1]
    assert "总资产: 4,000.00" in cost_unknown_section
    assert "总收益: 未知（成交成本信息不完整）" in cost_unknown_section
    assert "最大回撤: 未知（成交成本信息不完整）" in cost_unknown_section
    assert "夏普比率: 未知（成交成本信息不完整）" in cost_unknown_section
    assert "胜率: 未知（成交成本信息不完整）" in cost_unknown_section
    assert result["summaries"][3]["total_value"] == 4000.0
    assert result["summaries"][3]["total_return"] is None
    assert result["summaries"][3]["max_drawdown"] is None
    assert result["summaries"][3]["sharpe_ratio"] is None
    assert result["summaries"][3]["win_rate"] is None
    assert result["summaries"][1]["total_value"] is None
    assert result["summaries"][1]["total_return"] is None
    assert result["summaries"][1]["max_drawdown"] is None
    assert result["summaries"][1]["sharpe_ratio"] is None
    assert result["summaries"][2]["total_value"] is None
    assert result["summaries"][2]["total_return"] is None
    assert result["summaries"][2]["max_drawdown"] is None
    assert result["summaries"][2]["sharpe_ratio"] is None
    assert result["summaries"][1]["win_rate"] is None
    assert sent["recipients"] == settings.PERFORMANCE_SUMMARY_RECIPIENTS


def test_performance_summary_notification_and_repository_failures_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
    settings,
) -> None:
    """Notification failure is non-fatal while account repository failure is fatal."""
    account = SimpleNamespace(
        account_id=1,
        account_name="one",
        total_value=1000,
        cash_known=True,
    )
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
                "account": account,
                "positions": [],
                "performance": {
                    "total_return": 0.0,
                    "annual_return": 0.0,
                    "max_drawdown": 0.0,
                    "sharpe_ratio": 0.0,
                    "win_rate": 0.0,
                },
                "total_trades": 0,
                "total_positions": 0,
                "win_rate_known": True,
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
