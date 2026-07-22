from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain.entities import PortfolioSnapshot, TargetPortfolio, TargetPosition
from apps.portfolio.domain.services import build_transition_plan


def test_transition_plan_applies_t_plus_one_lots_liquidity_and_cash() -> None:
    now = datetime(2025, 3, 3, tzinfo=UTC)
    target = TargetPortfolio(
        target_id="target-1",
        decision_snapshot_id="decision-1",
        positions=(TargetPosition("BUY.SZ", Decimal("0.5")),),
        target_cash_weight=Decimal("0.5"),
        strategy_version="strategy-v1",
    )
    current = PortfolioSnapshot(
        snapshot_id="holdings-1",
        account_id="account-1",
        as_of_time=now,
        cash=Decimal("5000"),
        positions={"SELL.SZ": {"quantity": 200, "available_quantity": 100}},
    )

    plan = build_transition_plan(
        idempotency_key="rebalance-1",
        target=target,
        current=current,
        prices={"BUY.SZ": Decimal("10"), "SELL.SZ": Decimal("10")},
        market_facts={
            "BUY.SZ": {
                "volume": 1000,
                "suspended": False,
                "limit_up": False,
                "limit_down": False,
            },
            "SELL.SZ": {
                "volume": 10000,
                "suspended": False,
                "limit_up": False,
                "limit_down": False,
            },
        },
        config={
            "policy_version": "a-share-policy-v1",
            "buy_lot_size": 100,
            "fee_rate": "0.001",
            "slippage_rate": "0.001",
            "min_rebalance_value": "0",
            "max_volume_participation": "0.2",
            "max_asset_weight": "0.8",
        },
        expires_at=now + timedelta(hours=2),
    )

    sell = next(order for order in plan.orders if order.asset_code == "SELL.SZ")
    buy = next(order for order in plan.orders if order.asset_code == "BUY.SZ")
    assert [order.side for order in plan.orders] == ["sell", "buy"]
    assert sell.quantity == 100
    assert sell.remaining_quantity == 100
    assert any(item.rule_code == "t_plus_one" for item in sell.constraints)
    assert buy.quantity % 100 == 0
    assert buy.quantity <= 200
    assert plan.cash_after >= 0


def test_suspension_blocks_order_and_keeps_remainder() -> None:
    now = datetime(2025, 3, 3, tzinfo=UTC)
    target = TargetPortfolio(
        target_id="target-2",
        decision_snapshot_id="decision-2",
        positions=(TargetPosition("HALT.SZ", Decimal("0.5")),),
        target_cash_weight=Decimal("0.5"),
        strategy_version="strategy-v1",
    )
    current = PortfolioSnapshot("holdings-2", "account-1", now, Decimal("10000"), {})
    plan = build_transition_plan(
        idempotency_key="rebalance-2",
        target=target,
        current=current,
        prices={"HALT.SZ": Decimal("10")},
        market_facts={
            "HALT.SZ": {
                "suspended": True,
                "limit_up": False,
                "limit_down": False,
                "volume": 0,
            }
        },
        config={
            "policy_version": "a-share-policy-v1",
            "buy_lot_size": 100,
            "fee_rate": "0.001",
            "slippage_rate": "0.001",
            "min_rebalance_value": "0",
            "max_volume_participation": "0.2",
            "max_asset_weight": "0.8",
        },
        expires_at=now + timedelta(hours=1),
    )

    order = plan.orders[0]
    assert order.status == "blocked"
    assert order.quantity == 0
    assert order.remaining_quantity == 500


def test_transition_plan_fails_closed_on_incomplete_policy_or_market_facts() -> None:
    now = datetime(2025, 3, 3, tzinfo=UTC)
    target = TargetPortfolio(
        target_id="target-3",
        decision_snapshot_id="decision-3",
        positions=(TargetPosition("BUY.SZ", Decimal("0.5")),),
        target_cash_weight=Decimal("0.5"),
        strategy_version="strategy-v1",
    )
    current = PortfolioSnapshot("holdings-3", "account-1", now, Decimal("10000"), {})

    with pytest.raises(ValueError, match="planning policy is incomplete"):
        build_transition_plan(
            idempotency_key="rebalance-3",
            target=target,
            current=current,
            prices={"BUY.SZ": Decimal("10")},
            market_facts={"BUY.SZ": {}},
            config={"buy_lot_size": 100},
            expires_at=now + timedelta(hours=1),
        )
