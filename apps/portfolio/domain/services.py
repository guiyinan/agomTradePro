"""Deterministic portfolio-to-order conversion rules."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from .entities import (
    ConstraintDecision,
    OrderDraft,
    PortfolioSnapshot,
    TargetPortfolio,
    TransitionPlan,
)


def _round_buy_lot(quantity: int, lot_size: int) -> int:
    return max(0, quantity // lot_size * lot_size)


def build_transition_plan(
    *,
    idempotency_key: str,
    target: TargetPortfolio,
    current: PortfolioSnapshot,
    prices: dict[str, Decimal],
    market_facts: dict[str, dict[str, Any]],
    config: dict[str, Any],
    expires_at: datetime,
) -> TransitionPlan:
    """Build order drafts while preserving cash and configured A-share constraints."""

    target.validate()
    if current.as_of_time.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("portfolio plan timestamps must be timezone-aware")
    if expires_at <= current.as_of_time:
        raise ValueError("transition plan must expire after the portfolio snapshot")
    if current.cash < 0:
        raise ValueError("portfolio cash cannot be negative")
    required_config = {
        "policy_version",
        "buy_lot_size",
        "fee_rate",
        "slippage_rate",
        "min_rebalance_value",
        "max_asset_weight",
        "max_volume_participation",
    }
    missing_config = sorted(required_config - set(config))
    if missing_config:
        raise ValueError(f"planning policy is incomplete: {', '.join(missing_config)}")
    if not str(config["policy_version"]).strip():
        raise ValueError("planning policy_version is required")
    lot_size = int(config["buy_lot_size"])
    fee_rate = Decimal(str(config["fee_rate"]))
    slippage_rate = Decimal(str(config["slippage_rate"]))
    min_rebalance = Decimal(str(config["min_rebalance_value"]))
    max_weight = Decimal(str(config["max_asset_weight"]))
    participation = Decimal(str(config["max_volume_participation"]))
    if lot_size <= 0:
        raise ValueError("buy_lot_size must be positive")
    if not Decimal("0") <= fee_rate < Decimal("1"):
        raise ValueError("fee_rate must be within [0, 1)")
    if not Decimal("0") <= slippage_rate < Decimal("1"):
        raise ValueError("slippage_rate must be within [0, 1)")
    if min_rebalance < 0:
        raise ValueError("min_rebalance_value cannot be negative")
    if not Decimal("0") < max_weight <= Decimal("1"):
        raise ValueError("max_asset_weight must be within (0, 1]")
    if not Decimal("0") <= participation <= Decimal("1"):
        raise ValueError("max_volume_participation must be within [0, 1]")
    total_value = current.cash + sum(
        Decimal(str(position.get("quantity", 0))) * prices.get(code, Decimal("0"))
        for code, position in current.positions.items()
    )
    target_weights = {item.asset_code: item.target_weight for item in target.positions}
    codes = set(current.positions) | set(target_weights)
    planned_codes: list[tuple[bool, str]] = []
    for code in codes:
        price = prices.get(code)
        if price is None or price <= 0:
            raise ValueError(f"missing positive price for {code}")
        weight = target_weights.get(code, Decimal("0"))
        if weight > max_weight:
            raise ValueError(f"target weight exceeds configured maximum for {code}")
        held = int(current.positions.get(code, {}).get("quantity", 0))
        if held < 0:
            raise ValueError(f"position quantity cannot be negative for {code}")
        if code not in market_facts:
            raise ValueError(f"missing market facts for {code}")
        missing_facts = sorted(
            {"suspended", "limit_up", "limit_down", "volume"} - set(market_facts[code])
        )
        if missing_facts:
            raise ValueError(f"market facts are incomplete for {code}: {', '.join(missing_facts)}")
        target_qty = int((total_value * weight / price).to_integral_value(rounding=ROUND_DOWN))
        if target_qty < held and "available_quantity" not in current.positions.get(code, {}):
            raise ValueError(f"available_quantity is required for sell planning: {code}")
        # Sells must fund buys regardless of asset-code ordering.
        planned_codes.append((target_qty - held >= 0, code))
    orders: list[OrderDraft] = []
    all_constraints: list[ConstraintDecision] = []
    cash_after = current.cash
    for _, code in sorted(planned_codes):
        price = prices.get(code)
        assert price is not None
        weight = target_weights.get(code, Decimal("0"))
        held = int(current.positions.get(code, {}).get("quantity", 0))
        available = int(current.positions.get(code, {}).get("available_quantity", held))
        target_qty = int((total_value * weight / price).to_integral_value(rounding=ROUND_DOWN))
        raw_delta = target_qty - held
        if abs(Decimal(raw_delta) * price) < min_rebalance:
            continue
        side = "buy" if raw_delta > 0 else "sell"
        requested = abs(raw_delta)
        facts = market_facts.get(code, {})
        decisions: list[ConstraintDecision] = []
        allowed = requested
        if facts.get("suspended"):
            decisions.append(
                ConstraintDecision("trading_status", code, False, requested, 0, "suspended")
            )
            allowed = 0
        elif side == "buy" and facts.get("limit_up"):
            decisions.append(
                ConstraintDecision("price_limit", code, False, requested, 0, "limit_up")
            )
            allowed = 0
        elif side == "sell" and facts.get("limit_down"):
            decisions.append(
                ConstraintDecision("price_limit", code, False, requested, 0, "limit_down")
            )
            allowed = 0
        if side == "sell" and allowed > available:
            decisions.append(
                ConstraintDecision(
                    "t_plus_one", code, False, allowed, available, "available quantity"
                )
            )
            allowed = available
        if side == "buy" and allowed:
            rounded = _round_buy_lot(allowed, lot_size)
            if rounded != allowed:
                decisions.append(
                    ConstraintDecision(
                        "buy_lot", code, rounded > 0, allowed, rounded, "lot rounding"
                    )
                )
            allowed = rounded
        market_volume = int(facts.get("volume", 0) or 0)
        if market_volume < 0:
            raise ValueError(f"market volume cannot be negative for {code}")
        if allowed:
            liquidity_cap = int(Decimal(market_volume) * participation)
            if side == "buy":
                liquidity_cap = _round_buy_lot(liquidity_cap, lot_size)
            if allowed > liquidity_cap:
                decisions.append(
                    ConstraintDecision(
                        "liquidity",
                        code,
                        liquidity_cap > 0,
                        allowed,
                        liquidity_cap,
                        "participation cap",
                    )
                )
                allowed = liquidity_cap
        execution_price = price * (
            Decimal("1") + slippage_rate if side == "buy" else Decimal("1") - slippage_rate
        )
        fee = (Decimal(allowed) * execution_price * fee_rate).quantize(Decimal("0.01"))
        if side == "buy" and allowed:
            affordable = int(
                (cash_after / (execution_price * (Decimal("1") + fee_rate))).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            affordable = _round_buy_lot(affordable, lot_size)
            if allowed > affordable:
                decisions.append(
                    ConstraintDecision(
                        "cash", code, affordable > 0, allowed, affordable, "cash cap"
                    )
                )
                allowed = affordable
                fee = (Decimal(allowed) * execution_price * fee_rate).quantize(Decimal("0.01"))
            cash_after -= Decimal(allowed) * execution_price + fee
        elif side == "sell" and allowed:
            cash_after += Decimal(allowed) * execution_price - fee
        remaining = requested - allowed
        all_constraints.extend(decisions)
        orders.append(
            OrderDraft(
                asset_code=code,
                side=side,
                quantity=allowed,
                reference_price=execution_price,
                estimated_fee=fee,
                status="blocked" if allowed == 0 else ("partial" if remaining else "draft"),
                remaining_quantity=remaining,
                constraints=tuple(decisions),
            )
        )
    stable_id = uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key).hex
    return TransitionPlan(
        plan_id=stable_id,
        idempotency_key=idempotency_key,
        account_id=current.account_id,
        decision_snapshot_id=target.decision_snapshot_id,
        portfolio_snapshot_id=current.snapshot_id,
        target_portfolio_id=target.target_id,
        as_of_time=current.as_of_time,
        expires_at=expires_at,
        orders=tuple(orders),
        constraints=tuple(all_constraints),
        cash_before=current.cash,
        cash_after=cash_after,
        metadata={"planning_policy_version": str(config["policy_version"])},
    )
