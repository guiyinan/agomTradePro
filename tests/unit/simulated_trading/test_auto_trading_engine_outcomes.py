"""Outcome regressions for automatic trading account selection and failures."""

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.risk_center.application.trade_guard import PreTradeRiskCheckResult
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.ports import PositionExitAdvice
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingOutcome,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)


def _account(account_id: int = 17) -> SimulatedAccount:
    return SimulatedAccount(
        account_id=account_id,
        account_name=f"account-{account_id}",
        account_type=AccountType.SIMULATED,
        initial_capital=100_000.0,
        current_cash=100_000.0,
        current_market_value=0.0,
        total_value=100_000.0,
        auto_trading_enabled=True,
    )


def _engine_with_legacy_candidate(account: SimulatedAccount) -> tuple[AutoTradingEngine, Mock]:
    account_repo = Mock()
    account_repo.get_active_accounts.return_value = [account]
    position_repo = Mock()
    position_repo.get_by_account.return_value = []
    position_repo.get_position.return_value = None
    buy_use_case = Mock()
    sell_use_case = Mock()
    asset_pool_service = Mock()
    asset_pool_service.get_investable_assets_with_signals.return_value = [
        {
            "asset_code": "000001.SZ",
            "asset_name": "平安银行",
            "asset_type": "equity",
            "score": 90.0,
            "signal_id": 42,
        }
    ]
    engine = AutoTradingEngine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=Mock(),
        buy_use_case=buy_use_case,
        sell_use_case=sell_use_case,
        performance_use_case=Mock(),
        asset_pool_service=asset_pool_service,
        price_provider=Mock(get_price=Mock(return_value=10.0)),
        pre_trade_risk_guard=Mock(execute=Mock(return_value=PreTradeRiskCheckResult(passed=True))),
    )
    engine._update_account_performance = Mock(return_value=True)
    return engine, buy_use_case


def _trade_stub(trade_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        trade_id=trade_id,
        execution_time=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
    )


def _legacy_buy_trade(account_id: int = 17, trade_id: int = 23) -> SimulatedTrade:
    executed_at = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
    return SimulatedTrade(
        trade_id=trade_id,
        account_id=account_id,
        asset_code="000001.SZ",
        asset_name="平安银行",
        asset_type="equity",
        action=TradeAction.BUY,
        quantity=100.0,
        price=10.0,
        amount=1_000.0,
        order_date=date(2026, 10, 16),
        execution_date=date(2026, 10, 16),
        execution_time=executed_at,
    )


def _issue_codes(result: AccountAutoTradingOutcome) -> set[str]:
    return {issue.code for issue in result.issues}


def test_strategy_binding_read_failure_does_not_execute_legacy_candidate() -> None:
    """A failed strategy lookup must block rather than trade through legacy mode."""

    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    engine.position_repo.get_by_account.return_value = []

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        side_effect=RuntimeError("strategy store unavailable"),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    buy_use_case.execute.assert_not_called()
    assert result.outcome is AutoTradingOutcome.BLOCKED
    assert _issue_codes(result) == {"STRATEGY_BINDING_UNAVAILABLE"}


def test_real_and_unknown_account_types_block_before_strategy_or_ledger_access() -> None:
    for account_type in (AccountType.REAL, "unrecognized"):
        account = replace(_account(), account_type=account_type)
        engine, buy_use_case = _engine_with_legacy_candidate(account)
        facade = SimpleNamespace(get_active_strategy_id=Mock(return_value=None))

        with patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=facade,
        ):
            result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

        assert result.outcome is AutoTradingOutcome.BLOCKED
        assert _issue_codes(result) == {"AUTO_TRADING_ACCOUNT_TYPE_UNSUPPORTED"}
        facade.get_active_strategy_id.assert_not_called()
        engine.position_repo.get_by_account.assert_not_called()
        engine.position_repo.get_position.assert_not_called()
        engine.asset_pool_service.get_investable_assets_with_signals.assert_not_called()
        engine.price_provider.get_price.assert_not_called()
        buy_use_case.execute.assert_not_called()
        engine.sell_use_case.execute.assert_not_called()
        engine._update_account_performance.assert_not_called()


def test_candidate_source_failure_is_reported_instead_of_a_noop() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    engine.asset_pool_service.get_investable_assets_with_signals.side_effect = RuntimeError(
        "candidate source unavailable"
    )

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert _issue_codes(result) == {"BUY_CANDIDATE_READ_FAILED"}
    buy_use_case.execute.assert_not_called()


def test_account_position_read_failure_is_reported_without_buying() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    engine.position_repo.get_by_account.side_effect = RuntimeError("position store unavailable")

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert _issue_codes(result) == {"ACCOUNT_POSITION_READ_FAILED"}
    buy_use_case.execute.assert_not_called()


def test_missing_candidate_price_is_reported_as_blocked() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    engine.price_provider = Mock(
        get_price=Mock(return_value=None),
        require_price=Mock(return_value=None),
    )

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.BLOCKED
    assert _issue_codes(result) == {"BUY_PRICE_UNAVAILABLE"}
    buy_use_case.execute.assert_not_called()


def test_risk_rejection_is_reported_as_blocked() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    engine.pre_trade_risk_guard = Mock(
        execute=Mock(return_value=PreTradeRiskCheckResult(passed=False))
    )

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.BLOCKED
    assert _issue_codes(result) == {"PRE_TRADE_RISK_REJECTED"}
    buy_use_case.execute.assert_not_called()


def test_buy_use_case_exception_marks_write_effects_indeterminate() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    buy_use_case.execute.side_effect = RuntimeError("write outcome unknown")

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert result.confirmed_trade_count == 0
    assert result.stored is None
    assert result.counts_unavailable is True
    assert any(issue.effects_indeterminate for issue in result.issues)


def test_sell_use_case_exception_preserves_unknown_ledger_effects() -> None:
    account = _account()
    engine, _ = _engine_with_legacy_candidate(account)
    position = SimpleNamespace(
        asset_code="000001.SZ",
        asset_name="平安银行",
        quantity=100,
        available_quantity=100,
        available_quantity_known=True,
        unrealized_pnl_pct=0.0,
    )
    engine.position_repo.get_by_account.return_value = [position]
    engine._get_position_exit_advice = Mock(
        return_value=PositionExitAdvice(
            asset_code="000001.SZ",
            should_exit=True,
            quantity=100,
            reason_code="TEST_EXIT",
            reason_text="test exit",
        )
    )
    engine.sell_use_case.execute.side_effect = RuntimeError("write outcome unknown")
    engine.asset_pool_service.get_investable_assets_with_signals.return_value = []

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert result.confirmed_trade_count == 0
    assert result.stored is None
    assert _issue_codes(result) == {"SELL_EXECUTION_OUTCOME_UNKNOWN"}
    assert result.issues[0].effects_indeterminate is True


def test_confirmed_sell_survives_execution_link_failure_as_partial() -> None:
    account = _account()
    engine, _ = _engine_with_legacy_candidate(account)
    position = SimpleNamespace(
        asset_code="000001.SZ",
        asset_name="平安银行",
        quantity=100,
        available_quantity=100,
        available_quantity_known=True,
        unrealized_pnl_pct=0.0,
    )
    engine.position_repo.get_by_account.return_value = [position]
    engine._get_position_exit_advice = Mock(
        return_value=PositionExitAdvice(
            asset_code="000001.SZ",
            should_exit=True,
            quantity=100,
            reason_code="TEST_EXIT",
            reason_text="test exit",
        )
    )
    engine.sell_use_case.execute.return_value = _trade_stub()
    engine.execution_link_recorder = Mock(
        record_execution=Mock(side_effect=RuntimeError("link store unavailable"))
    )
    engine.asset_pool_service.get_investable_assets_with_signals.return_value = []

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.PARTIAL
    assert result.sell_count == 1
    assert result.confirmed_trade_count == 1
    assert result.stored == 1
    assert _issue_codes(result) == {"EXECUTION_LINK_RECORD_FAILED"}


def test_legacy_buy_records_execution_link_from_confirmed_trade() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    trade = _legacy_buy_trade(account_id=account.account_id)
    buy_use_case.execute.return_value = trade
    engine.execution_link_recorder = Mock(
        record_execution=Mock(return_value={"execution_link_id": 91})
    )

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
        ),
        patch(
            "apps.simulated_trading.application.auto_trading_engine.PositionSizingRule.calculate_buy_quantity",
            return_value=100,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.SUCCESS
    assert result.buy_count == 1
    assert result.confirmed_trade_count == 1
    engine.execution_link_recorder.record_execution.assert_called_once_with(
        recommendation_id=None,
        transaction_id=trade.trade_id,
        account_id=account.account_id,
        security_code=trade.asset_code,
        actual_action="buy",
        executed_at=trade.execution_time,
        match_if_missing=True,
        notes="Auto legacy buy",
    )


def test_legacy_buy_link_failure_preserves_confirmed_trade_as_partial() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    trade = _legacy_buy_trade(account_id=account.account_id)
    buy_use_case.execute.return_value = trade
    engine.execution_link_recorder = Mock(
        record_execution=Mock(side_effect=RuntimeError("link store unavailable"))
    )

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
        ),
        patch(
            "apps.simulated_trading.application.auto_trading_engine.PositionSizingRule.calculate_buy_quantity",
            return_value=100,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.PARTIAL
    assert result.buy_count == 1
    assert result.confirmed_trade_count == 1
    assert result.stored == 1
    assert _issue_codes(result) == {"EXECUTION_LINK_RECORD_FAILED"}
    assert result.issues[0].effects_indeterminate is False
    engine.execution_link_recorder.record_execution.assert_called_once_with(
        recommendation_id=None,
        transaction_id=trade.trade_id,
        account_id=account.account_id,
        security_code=trade.asset_code,
        actual_action="buy",
        executed_at=trade.execution_time,
        match_if_missing=True,
        notes="Auto legacy buy",
    )


def test_performance_failure_does_not_erase_confirmed_buy() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    buy_use_case.execute.return_value = _trade_stub()
    engine._update_account_performance = Mock(return_value=False)

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=None)),
        ),
        patch(
            "apps.simulated_trading.application.auto_trading_engine.PositionSizingRule.calculate_buy_quantity",
            return_value=100,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.PARTIAL
    assert result.buy_count == 1
    assert result.confirmed_trade_count == 1
    assert _issue_codes(result) == {"ACCOUNT_PERFORMANCE_UPDATE_FAILED"}


def test_strategy_execution_failure_is_not_reported_as_noop() -> None:
    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    gateway = Mock()
    gateway.execute_for_account.return_value = SimpleNamespace(
        success=False,
        signals=[],
        error_message="private error details",
    )

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=91)),
        ),
        patch(
            "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
            return_value=gateway,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert _issue_codes(result) == {"STRATEGY_EXECUTION_FAILED"}
    assert "private error details" not in str(result.to_payload())
    buy_use_case.execute.assert_not_called()


def test_strategy_sell_exception_marks_unknown_effects_without_losing_result() -> None:
    from apps.strategy.application.execution_gateway import ExecutionResult, SignalInfo

    account = _account()
    engine, _ = _engine_with_legacy_candidate(account)
    engine.position_repo.get_by_account.return_value = [
        SimpleNamespace(
            asset_code="000001.SZ",
            asset_name="平安银行",
            quantity=100,
            available_quantity=100,
            available_quantity_known=True,
        )
    ]
    engine.sell_use_case.execute.side_effect = RuntimeError("private storage error")
    signal = SignalInfo(
        signal_id=42,
        asset_code="000001.SZ",
        asset_name="平安银行",
        action="sell",
        quantity=100,
        confidence=0.9,
        reason="test signal",
    )
    gateway = Mock()
    gateway.execute_for_account.return_value = ExecutionResult(success=True, signals=[signal])

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=91)),
        ),
        patch(
            "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
            return_value=gateway,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert result.sell_count == 0
    assert result.stored is None
    assert _issue_codes(result) == {"SELL_EXECUTION_OUTCOME_UNKNOWN"}
    assert result.issues[0].effects_indeterminate is True
    assert "private storage error" not in str(result.to_payload())


def test_strategy_buy_exception_marks_unknown_effects() -> None:
    from apps.strategy.application.execution_gateway import ExecutionResult, SignalInfo

    account = _account()
    engine, buy_use_case = _engine_with_legacy_candidate(account)
    buy_use_case.execute.side_effect = RuntimeError("private storage error")
    signal = SignalInfo(
        signal_id=42,
        asset_code="000001.SZ",
        asset_name="平安银行",
        action="buy",
        quantity=100,
        confidence=0.9,
        reason="test signal",
    )
    gateway = Mock()
    gateway.execute_for_account.return_value = ExecutionResult(success=True, signals=[signal])

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=91)),
        ),
        patch(
            "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
            return_value=gateway,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.FAILED
    assert result.buy_count == 0
    assert result.stored is None
    assert _issue_codes(result) == {"BUY_EXECUTION_OUTCOME_UNKNOWN"}
    assert result.issues[0].effects_indeterminate is True
    assert "private storage error" not in str(result.to_payload())


def test_strategy_buy_and_sell_success_return_typed_counts() -> None:
    from apps.strategy.application.execution_gateway import ExecutionResult, SignalInfo

    for action in ("buy", "sell"):
        account = _account()
        engine, buy_use_case = _engine_with_legacy_candidate(account)
        engine._update_account_performance = Mock(return_value=True)
        signal = SignalInfo(
            signal_id=42,
            asset_code="000001.SZ",
            asset_name="平安银行",
            action=action,
            quantity=100,
            confidence=0.9,
            reason="test signal",
        )
        if action == "sell":
            engine.position_repo.get_by_account.return_value = [
                SimpleNamespace(
                    asset_code="000001.SZ",
                    asset_name="平安银行",
                    quantity=100,
                    available_quantity=100,
                    available_quantity_known=True,
                )
            ]
        gateway = Mock()
        gateway.execute_for_account.return_value = ExecutionResult(success=True, signals=[signal])

        with (
            patch(
                "apps.simulated_trading.application.facade.get_simulated_trading_facade",
                return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=91)),
            ),
            patch(
                "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
                return_value=gateway,
            ),
        ):
            result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

        assert result.outcome is AutoTradingOutcome.SUCCESS
        assert result.buy_count == (1 if action == "buy" else 0)
        assert result.sell_count == (1 if action == "sell" else 0)
        if action == "buy":
            buy_use_case.execute.assert_called_once()
            engine.sell_use_case.execute.assert_not_called()
        else:
            engine.sell_use_case.execute.assert_called_once()
            buy_use_case.execute.assert_not_called()


def test_failure_is_isolated_to_its_account() -> None:
    first = _account(17)
    second = _account(18)
    engine, buy_use_case = _engine_with_legacy_candidate(first)
    engine.account_repo.get_active_accounts.return_value = [first, second]
    engine.asset_pool_service.get_investable_assets_with_signals.return_value = []

    def strategy_for_account(account_id: int) -> None:
        if account_id == first.account_id:
            raise RuntimeError("first account assignment unavailable")
        return None

    with patch(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        return_value=SimpleNamespace(get_active_strategy_id=Mock(side_effect=strategy_for_account)),
    ):
        results = engine.run_daily_trading(date(2026, 10, 16))

    assert results[first.account_id].outcome is AutoTradingOutcome.BLOCKED
    assert _issue_codes(results[first.account_id]) == {"STRATEGY_BINDING_UNAVAILABLE"}
    assert results[second.account_id].outcome is AutoTradingOutcome.NOOP
    buy_use_case.execute.assert_not_called()


def test_strategy_sell_unknown_available_quantity_blocks_before_quote_or_write() -> None:
    """An unknown balance is a determinate block before price or sell side effects."""

    from apps.strategy.application.execution_gateway import ExecutionResult, SignalInfo

    account = _account()
    engine, _ = _engine_with_legacy_candidate(account)
    engine._update_account_performance = Mock(return_value=True)
    engine.position_repo.get_by_account.return_value = [
        SimpleNamespace(
            asset_code="000001.SZ",
            asset_name="平安银行",
            quantity=100,
            available_quantity=100,
            available_quantity_known=False,
            unrealized_pnl_pct=0.0,
        )
    ]
    signal = SignalInfo(
        signal_id=91,
        asset_code="000001.SZ",
        asset_name="平安银行",
        action="sell",
        quantity=100,
        confidence=0.9,
        reason="unknown sellable balance",
    )
    gateway = Mock()
    gateway.execute_for_account.return_value = ExecutionResult(success=True, signals=[signal])
    price_provider = Mock(
        get_price=Mock(return_value=10.0),
        require_price=Mock(return_value=10.0),
    )
    engine.price_provider = price_provider
    trade_repo = Mock()
    engine.trade_repo = trade_repo
    execution_link_recorder = Mock()
    engine.execution_link_recorder = execution_link_recorder

    with (
        patch(
            "apps.simulated_trading.application.facade.get_simulated_trading_facade",
            return_value=SimpleNamespace(get_active_strategy_id=Mock(return_value=91)),
        ),
        patch(
            "apps.strategy.application.execution_gateway.get_strategy_execution_gateway",
            return_value=gateway,
        ),
    ):
        result = engine.run_daily_trading(date(2026, 10, 16))[account.account_id]

    assert result.outcome is AutoTradingOutcome.BLOCKED
    assert _issue_codes(result) == {"SELLABLE_BALANCE_UNKNOWN"}
    assert result.confirmed_trade_count == 0
    assert result.issues[0].effects_indeterminate is False
    engine.sell_use_case.execute.assert_not_called()
    price_provider.get_price.assert_not_called()
    price_provider.require_price.assert_not_called()
    assert trade_repo.mock_calls == []
    execution_link_recorder.record_execution.assert_not_called()
