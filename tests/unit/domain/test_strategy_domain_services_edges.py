"""Decision, sizing, order-state, and pre-trade risk tests for Strategy."""

import pytest

from apps.strategy.domain.entities import DecisionAction, OrderEvent, OrderStatus
from apps.strategy.domain.rules import (
    apply_order_event,
    can_apply_order_event,
    is_terminal_order_status,
)
from apps.strategy.domain.services import (
    DecisionPolicyEngine,
    OrderStateMachine,
    PreTradeRiskGate,
    SizingEngine,
)


def test_order_state_machine_covers_paths_terminal_states_and_invalid_events() -> None:
    """Only declared order transitions can advance the lifecycle."""
    assert can_apply_order_event(OrderStatus.DRAFT, OrderEvent.SUBMIT) is True
    assert apply_order_event(OrderStatus.DRAFT, OrderEvent.SUBMIT) == OrderStatus.PENDING_APPROVAL
    assert is_terminal_order_status(OrderStatus.FILLED) is True
    assert is_terminal_order_status(OrderStatus.SENT) is False
    assert set(OrderStateMachine.get_valid_events(OrderStatus.SENT)) == {
        OrderEvent.PARTIAL_FILL,
        OrderEvent.FILL,
        OrderEvent.CANCEL,
        OrderEvent.FAIL,
    }
    with pytest.raises(ValueError, match="Invalid transition"):
        OrderStateMachine.transition(OrderStatus.DRAFT, OrderEvent.FILL)
    assert OrderStateMachine.validate_transition_path([]) is False
    assert (
        OrderStateMachine.validate_transition_path(
            [
                (OrderStatus.DRAFT, OrderEvent.SUBMIT),
                (OrderStatus.PENDING_APPROVAL, OrderEvent.APPROVE),
                (OrderStatus.APPROVED, OrderEvent.SEND),
                (OrderStatus.SENT, OrderEvent.FILL),
            ]
        )
        is True
    )
    assert (
        OrderStateMachine.validate_transition_path(
            [
                (OrderStatus.DRAFT, OrderEvent.SUBMIT),
                (OrderStatus.PENDING_APPROVAL, OrderEvent.FILL),
            ]
        )
        is False
    )


def _decision(**changes: object) -> tuple[str, list[str], str, float | None]:
    """Evaluate a decision from valid defaults plus one boundary change."""
    values: dict[str, object] = {
        "signal_strength": 0.8,
        "signal_direction": "bullish",
        "signal_confidence": 0.8,
        "regime": "Recovery",
        "regime_confidence": 0.8,
        "daily_pnl_pct": 0.0,
        "daily_trade_count": 0,
        "volatility_z": 1.0,
        "target_regime": "Recovery",
    }
    values.update(changes)
    return DecisionPolicyEngine().evaluate(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"daily_pnl_pct": -5.0}, "DAILY_LOSS_LIMIT"),
        ({"daily_trade_count": 10}, "DAILY_TRADE_LIMIT"),
        ({"volatility_z": 3.1}, "VOLATILITY_TOO_HIGH"),
        ({"signal_strength": 0.59}, "SIGNAL_WEAK"),
        ({"target_regime": "Deflation"}, "REGIME_MISMATCH"),
    ],
)
def test_decision_policy_denies_each_hard_limit(changes: dict[str, object], reason: str) -> None:
    """Each hard limit has one stable auditable reason code."""
    action, reasons, _, valid_until = _decision(**changes)
    assert action == DecisionAction.DENY.value
    assert reasons == [reason]
    assert valid_until is None


def test_decision_policy_watch_and_allow_paths() -> None:
    """Low confidence becomes WATCH while strong aligned evidence is ALLOW."""
    action, reasons, _, valid_until = _decision(signal_confidence=0.69)
    assert (action, reasons, valid_until) == (
        DecisionAction.WATCH.value,
        ["LOW_CONFIDENCE"],
        300,
    )
    action, reasons, text, valid_until = _decision(regime_confidence=0.49)
    assert action == DecisionAction.WATCH.value
    assert reasons == ["LOW_CONFIDENCE"]
    assert "0.49" in text
    assert valid_until == 300

    action, reasons, text, valid_until = _decision()
    assert action == DecisionAction.ALLOW.value
    assert reasons == ["SIGNAL_STRONG", "REGIME_ALIGNED"]
    assert "0.80" in text
    assert valid_until == 3600

    unaligned_allowed = DecisionPolicyEngine(regime_alignment_required=False).evaluate(
        signal_strength=0.8,
        signal_direction="bullish",
        signal_confidence=0.8,
        regime="Recovery",
        regime_confidence=0.8,
        daily_pnl_pct=0,
        daily_trade_count=0,
        target_regime="Deflation",
    )
    assert unaligned_allowed[0] == DecisionAction.ALLOW.value
    assert unaligned_allowed[1] == ["SIGNAL_STRONG"]


def test_sizing_engine_fixed_fraction_default_and_atr_paths() -> None:
    """Sizing remains capped, minimum-sized, and explicit about fallbacks."""
    engine = SizingEngine(
        risk_per_trade_pct=1.0,
        max_position_pct=20.0,
        min_qty=1,
    )
    notional, qty, risk, method, explanation = engine.calculate(
        "fixed_fraction",
        account_equity=100_000,
        current_price=100,
        stop_loss_price=95,
    )
    assert (notional, qty, risk, method) == (20_000, 200, 1.0, "fixed_fraction")
    assert "固定风险比例" in explanation

    fallback = engine.calculate(
        "unknown",
        account_equity=100_000,
        current_price=100,
    )
    assert fallback[1:4] == (200, 20.0, "fixed_fraction")

    invalid_atr = engine.calculate(
        "atr_risk",
        account_equity=100_000,
        current_price=100,
        atr=0,
    )
    assert invalid_atr[3] == "fixed_fraction"

    atr = engine.calculate(
        "atr_risk",
        account_equity=100_000,
        current_price=100,
        atr=2,
        atr_risk_multiplier=2,
    )
    assert atr[1] == 200
    assert atr[2] == pytest.approx(0.8)
    assert atr[3] == "atr_risk"

    minimum = SizingEngine(min_qty=10).calculate(
        "fixed_fraction",
        account_equity=1,
        current_price=100,
    )
    assert minimum[1] == 10


def test_pre_trade_risk_gate_passes_safe_order_and_warns_without_volume() -> None:
    """A safe order passes while unavailable liquidity is a visible warning."""
    passed, violations, warnings, details = PreTradeRiskGate().check(
        symbol="000001.SZ",
        side="buy",
        qty=10,
        price=10,
        account_equity=100_000,
        current_position_value=0,
        daily_trade_count=0,
        daily_pnl_pct=0,
        avg_volume=None,
    )
    assert passed is True
    assert violations == []
    assert warnings == ["无法获取成交量数据，跳过流动性检查"]
    assert details["position_check"]["new_position_pct"] == pytest.approx(0.1)


def test_pre_trade_risk_gate_collects_all_hard_limits_and_warnings() -> None:
    """Position, count, loss, liquidity, and large-order checks are cumulative."""
    passed, violations, warnings, details = PreTradeRiskGate(
        max_single_position_pct=20,
        max_daily_trades=10,
        max_daily_loss_pct=5,
        min_volume=100_000,
    ).check(
        symbol="000001.SZ",
        side="buy",
        qty=300,
        price=100,
        account_equity=100_000,
        current_position_value=0,
        daily_trade_count=10,
        daily_pnl_pct=-5,
        avg_volume=1_000,
    )
    assert passed is False
    assert len(violations) == 4
    assert any("仓位超限" in item for item in violations)
    assert any("交易次数" in item for item in violations)
    assert any("日亏损" in item for item in violations)
    assert any("流动性不足" in item for item in violations)
    assert warnings and "大单警告" in warnings[0]
    assert details["liquidity_check"]["avg_volume"] == 1_000


def test_pre_trade_sell_and_zero_equity_are_safe_from_division_errors() -> None:
    """Sell checks and empty-account facts never divide by zero."""
    passed, violations, _, details = PreTradeRiskGate().check(
        symbol="000001.SZ",
        side="sell",
        qty=10,
        price=10,
        account_equity=0,
        current_position_value=100,
        daily_trade_count=0,
        daily_pnl_pct=0,
        avg_volume=1_000_000,
    )
    assert passed is True
    assert violations == []
    assert details["position_check"]["new_position_pct"] == 0
