"""Synthetic, source-labelled inputs shared by execution contract tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionMarketEvidence,
    ExecutionOrder,
    ExecutionQuantityConstraint,
    ExecutionSide,
    PriceBoundaryMode,
    SecurityTradingState,
    SellOddLotMode,
    SessionState,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)


def execution_order() -> ExecutionOrder:
    """Return an exact test order without implying live execution authority."""

    return ExecutionOrder(
        order_id="order-test",
        account_id=7,
        security_id="TEST.SECURITY",
        side=ExecutionSide.BUY,
        quantity=Decimal("200"),
        limit_price=Decimal("10"),
        sell_position_evidence=None,
    )


def execution_rule(*, security_id: str = "TEST.SECURITY") -> AShareExecutionRule:
    """Return a sealed synthetic v1 rule with explicit fixture provenance."""

    return AShareExecutionRule(
        rule_id="fixture-rule",
        rule_version="fixture-only",
        security_id=security_id,
        market="fixture-market",
        board="fixture-board",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"), step=Decimal("100"), maximum=Decimal("10000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="fixture-rule-source",
        rule_source_version="fixture-only",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(days=1),
        source_available_at=AS_OF - timedelta(days=1),
        effective_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=1),
    )


def execution_market() -> ExecutionMarketEvidence:
    """Return one synthetic market/session snapshot with a thirty-second quote window."""

    return ExecutionMarketEvidence(
        security_id="TEST.SECURITY",
        market="fixture-market",
        board="fixture-board",
        trading_date=AS_OF.date(),
        calendar_id="fixture-calendar",
        calendar_version="fixture-only",
        calendar_source_hash="b" * 64,
        calendar_observed_at=AS_OF - timedelta(days=1),
        calendar_available_at=AS_OF - timedelta(days=1),
        calendar_valid_until=AS_OF + timedelta(days=1),
        session_id="fixture-session",
        session_timezone="Asia/Shanghai",
        session_open_at=AS_OF - timedelta(minutes=30),
        session_close_at=AS_OF + timedelta(minutes=90),
        session_state=SessionState.OPEN,
        security_state=SecurityTradingState.TRADING,
        market_source_id="fixture-market-source",
        market_source_version="fixture-only",
        market_source_hash="c" * 64,
        price_boundary_mode=PriceBoundaryMode.LIMITED,
        lower_limit_price=Decimal("9"),
        upper_limit_price=Decimal("11"),
        reference_price=Decimal("10"),
        market_observed_at=AS_OF - timedelta(seconds=1),
        market_available_at=AS_OF,
        market_valid_until=AS_OF + timedelta(seconds=30),
    )
