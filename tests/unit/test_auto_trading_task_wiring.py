"""Task wiring tests for daily auto trading."""

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID

from tests.unit.simulated_trading.test_automatic_invocation_application import (
    _MemoryInvocationRepository,
)


def test_daily_auto_trading_task_uses_the_guarded_engine_builder():
    from apps.simulated_trading.domain.auto_trading_outcomes import (
        AccountAutoTradingOutcome,
    )

    engine = MagicMock()
    account_outcome = AccountAutoTradingOutcome(account_id=1, buy_count=1, sell_count=2)
    engine.run_daily_trading.return_value = {1: account_outcome}

    with (
        patch(
            "apps.simulated_trading.application.tasks.get_auto_invocation_repository",
            return_value=_MemoryInvocationRepository(),
        ),
        patch(
            "apps.simulated_trading.application.tasks.build_auto_trading_engine",
            return_value=engine,
        ) as engine_builder,
    ):
        from apps.simulated_trading.application.tasks import daily_auto_trading_task

        result = daily_auto_trading_task.run(
            trade_date="2026-04-30",
            account_ids=[1],
            invocation_key="task-wiring-run-001",
        )

    engine_builder.assert_called_once()
    invocation_id = engine_builder.call_args.kwargs["invocation_id"]
    assert isinstance(invocation_id, UUID)
    engine.run_daily_trading.assert_called_once_with(date(2026, 4, 30), account_ids=[1])
    account_payload = account_outcome.to_payload()
    assert result == {
        "outcome": "success",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "partial_account_count": 0,
        "stored": 3,
        "counts_unavailable": False,
        "buy_count": 1,
        "sell_count": 2,
        "confirmed_trade_count": 3,
        "reason_code": None,
        "accounts": [account_payload],
        "trade_date": "2026-04-30",
        "total_accounts": 1,
        "results": {1: account_payload},
        "summary": {
            "total_buy_count": 1,
            "total_sell_count": 2,
            "confirmed_trade_count": 3,
            "stored_trade_count": 3,
            "counts_unavailable": False,
        },
        "stable_error_code": None,
        "count_unit": "account",
        "stored_count_unit": "trade",
        "count_units": {
            "requested": "account",
            "succeeded": "account",
            "failed": "account",
            "partial_account_count": "account",
            "buy_count": "trade",
            "sell_count": "trade",
            "confirmed_trade_count": "trade",
            "stored": "trade",
        },
    }
    account_payload = account_outcome.to_payload()
    assert result == {
        "outcome": "success",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "partial_account_count": 0,
        "stored": 3,
        "counts_unavailable": False,
        "buy_count": 1,
        "sell_count": 2,
        "confirmed_trade_count": 3,
        "reason_code": None,
        "accounts": [account_payload],
        "trade_date": "2026-04-30",
        "total_accounts": 1,
        "results": {1: account_payload},
        "summary": {
            "total_buy_count": 1,
            "total_sell_count": 2,
            "confirmed_trade_count": 3,
            "stored_trade_count": 3,
            "counts_unavailable": False,
        },
        "stable_error_code": None,
        "count_unit": "account",
        "stored_count_unit": "trade",
        "count_units": {
            "requested": "account",
            "succeeded": "account",
            "failed": "account",
            "partial_account_count": "account",
            "buy_count": "trade",
            "sell_count": "trade",
            "confirmed_trade_count": "trade",
            "stored": "trade",
        },
    }


def test_update_all_prices_after_close_uses_local_realtime_polling_helper():
    snapshot = {
        "total_assets": 2,
        "success_count": 2,
        "failed_count": 0,
        "success_rate": 1.0,
    }

    with patch(
        "apps.simulated_trading.application.tasks.execute_realtime_price_polling",
        return_value=snapshot,
    ) as polling_helper:
        from apps.simulated_trading.application.tasks import update_all_prices_after_close

        result = update_all_prices_after_close.run()

    polling_helper.assert_called_once_with()
    assert result == {
        "outcome": "success",
        "success": True,
        "requested": 2,
        "succeeded": 2,
        "failed": 0,
        "stored": 2,
        "account_id": None,
        "snapshot": snapshot,
    }
