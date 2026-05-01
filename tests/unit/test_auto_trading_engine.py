"""Auto trading engine exit loop tests."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.ports import PositionExitAdvice


def _build_engine(*, positions, exit_advisor=None, signal_service=None):
    position_repo = Mock()
    position_repo.get_by_account.return_value = positions

    engine = AutoTradingEngine(
        account_repo=Mock(),
        position_repo=position_repo,
        trade_repo=Mock(),
        buy_use_case=Mock(),
        sell_use_case=Mock(),
        performance_use_case=Mock(),
        price_provider=Mock(get_price=Mock(return_value=10.0)),
        signal_service=signal_service,
        exit_advisor=exit_advisor,
    )
    engine._get_buy_candidates = Mock(return_value=[])
    engine._update_account_performance = Mock()
    return engine


def _build_account():
    return SimpleNamespace(
        account_id=1,
        account_name="test",
        current_cash=100000.0,
        current_market_value=10000.0,
        stop_loss_pct=10.0,
    )


def _build_position(**overrides):
    payload = {
        "asset_code": "000001.SZ",
        "asset_name": "平安银行",
        "quantity": 1000,
        "signal_id": None,
        "is_invalidated": False,
        "invalidation_reason": None,
        "unrealized_pnl_pct": 0.0,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_invalidated_position_has_highest_exit_priority():
    position = _build_position(
        is_invalidated=True,
        invalidation_reason="PMI 跌破阈值",
    )
    exit_advisor = Mock()
    exit_advisor.get_exit_advices.return_value = [
        PositionExitAdvice(
            asset_code="000001.SZ",
            should_reduce=True,
            quantity=200,
            reason_code="TRANSITION_PLAN_REDUCE",
            reason_text="减仓 200 股",
            source="decision_rhythm.transition_plan",
        )
    ]
    engine = _build_engine(positions=[position], exit_advisor=exit_advisor)

    buy_count, sell_count = engine._execute_legacy_trading(_build_account(), date(2026, 4, 30))

    assert buy_count == 0
    assert sell_count == 1
    engine.sell_use_case.execute.assert_called_once()
    assert engine.sell_use_case.execute.call_args.kwargs["quantity"] == 1000
    assert engine.sell_use_case.execute.call_args.kwargs["reason"] == "PMI 跌破阈值"


def test_exit_advisor_reduce_generates_partial_sell():
    position = _build_position()
    exit_advisor = Mock()
    exit_advisor.get_exit_advices.return_value = [
        PositionExitAdvice(
            asset_code="000001.SZ",
            should_reduce=True,
            quantity=300,
            reason_code="TRANSITION_PLAN_REDUCE",
            reason_text="统一调仓建议减仓",
            source="decision_rhythm.transition_plan",
        )
    ]
    engine = _build_engine(positions=[position], exit_advisor=exit_advisor)

    buy_count, sell_count = engine._execute_legacy_trading(_build_account(), date(2026, 4, 30))

    assert buy_count == 0
    assert sell_count == 1
    engine.sell_use_case.execute.assert_called_once()
    assert engine.sell_use_case.execute.call_args.kwargs["quantity"] == 300
    assert engine.sell_use_case.execute.call_args.kwargs["reason"] == "统一调仓建议减仓"


def test_exit_advisor_absent_falls_back_to_legacy_signal_invalid_logic():
    position = _build_position(signal_id=11)
    signal_service = Mock()
    signal_service.get_signal_by_id.return_value = {"is_valid": False}
    engine = _build_engine(positions=[position], signal_service=signal_service)

    advice = engine._get_position_exit_advice(
        position=position,
        account=_build_account(),
        trade_date=date(2026, 4, 30),
        advisor_map={},
    )

    assert advice is not None
    assert advice.should_exit is True
    assert advice.reason_code == "SIGNAL_INVALID"
