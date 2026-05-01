"""Task wiring tests for daily auto trading."""

from datetime import date
from unittest.mock import MagicMock, patch


def test_daily_auto_trading_task_injects_decision_rhythm_exit_advisor():
    account_repo = object()
    position_repo = object()
    trade_repo = object()
    signal_repo = object()
    asset_pool_repo = object()
    buy_use_case = object()
    sell_use_case = object()
    performance_use_case = object()
    price_provider = object()
    asset_pool_service = object()
    exit_advisor = object()
    engine = MagicMock()
    engine.run_daily_trading.return_value = {1: {"buy_count": 1, "sell_count": 2}}

    with (
        patch(
            "apps.simulated_trading.application.tasks.get_simulated_account_repository",
            return_value=account_repo,
        ),
        patch(
            "apps.simulated_trading.application.tasks.get_simulated_position_repository",
            return_value=position_repo,
        ),
        patch(
            "apps.simulated_trading.application.tasks.get_simulated_trade_repository",
            return_value=trade_repo,
        ),
        patch(
            "apps.simulated_trading.application.tasks.get_signal_repository",
            return_value=signal_repo,
        ),
        patch(
            "apps.simulated_trading.application.tasks.get_asset_pool_query_repository",
            return_value=asset_pool_repo,
        ),
        patch(
            "apps.simulated_trading.application.tasks.ExecuteBuyOrderUseCase",
            return_value=buy_use_case,
        ) as buy_use_case_cls,
        patch(
            "apps.simulated_trading.application.tasks.ExecuteSellOrderUseCase",
            return_value=sell_use_case,
        ) as sell_use_case_cls,
        patch(
            "apps.simulated_trading.application.tasks.GetAccountPerformanceUseCase",
            return_value=performance_use_case,
        ) as performance_use_case_cls,
        patch(
            "apps.simulated_trading.application.tasks.UnifiedPriceService",
            return_value=price_provider,
        ) as price_provider_cls,
        patch(
            "apps.simulated_trading.application.tasks.AssetPoolQueryService",
            return_value=asset_pool_service,
        ) as asset_pool_service_cls,
        patch(
            "apps.decision_rhythm.application.exit_advisors.build_decision_rhythm_exit_advisor",
            return_value=exit_advisor,
        ) as exit_advisor_builder,
        patch(
            "apps.simulated_trading.application.tasks.AutoTradingEngine",
            return_value=engine,
        ) as engine_cls,
    ):
        from apps.simulated_trading.application.tasks import daily_auto_trading_task

        result = daily_auto_trading_task.run(trade_date="2026-04-30", account_ids=[1])

    buy_use_case_cls.assert_called_once_with(
        account_repo,
        position_repo,
        trade_repo,
        signal_repo=signal_repo,
    )
    sell_use_case_cls.assert_called_once_with(account_repo, position_repo, trade_repo)
    performance_use_case_cls.assert_called_once_with(account_repo, position_repo, trade_repo)
    price_provider_cls.assert_called_once_with()
    asset_pool_service_cls.assert_called_once_with(
        asset_pool_repo=asset_pool_repo,
        signal_repo=signal_repo,
    )
    exit_advisor_builder.assert_called_once_with()
    engine_cls.assert_called_once_with(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        buy_use_case=buy_use_case,
        sell_use_case=sell_use_case,
        performance_use_case=performance_use_case,
        asset_pool_service=asset_pool_service,
        price_provider=price_provider,
        signal_service=signal_repo,
        exit_advisor=exit_advisor,
    )
    engine.run_daily_trading.assert_called_once_with(date(2026, 4, 30), account_ids=[1])
    assert result == {
        "success": True,
        "trade_date": "2026-04-30",
        "total_accounts": 1,
        "results": {1: {"buy_count": 1, "sell_count": 2}},
        "summary": {
            "total_buy_count": 1,
            "total_sell_count": 2,
        },
    }
