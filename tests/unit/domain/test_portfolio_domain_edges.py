"""Fail-closed target and transition planning tests for Portfolio."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain.entities import (
    PortfolioSnapshot,
    TargetPortfolio,
    TargetPosition,
)
from apps.portfolio.domain.services import build_transition_plan


def _target(
    *,
    target_id: str = "target-1",
    decision_snapshot_id: str = "decision-1",
    strategy_version: str = "v1",
    positions: tuple[TargetPosition, ...] = (TargetPosition("000001.SZ", Decimal("0.5")),),
    cash: Decimal = Decimal("0.5"),
) -> TargetPortfolio:
    """Build a target portfolio."""
    return TargetPortfolio(
        target_id=target_id,
        decision_snapshot_id=decision_snapshot_id,
        positions=positions,
        target_cash_weight=cash,
        strategy_version=strategy_version,
    )


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (_target(target_id=""), "target_id"),
        (_target(decision_snapshot_id=""), "decision_snapshot_id"),
        (_target(strategy_version=""), "strategy_version"),
        (
            _target(
                positions=(
                    TargetPosition("000001.SZ", Decimal("0.25")),
                    TargetPosition("000001.SZ", Decimal("0.25")),
                )
            ),
            "duplicate",
        ),
        (_target(cash=Decimal("0.4")), "sum to 1"),
        (
            _target(
                positions=(TargetPosition("000001.SZ", Decimal("-0.1")),),
                cash=Decimal("1.1"),
            ),
            "negative",
        ),
    ],
)
def test_target_portfolio_validation_rejects_invalid_identity_and_weights(
    target: TargetPortfolio, message: str
) -> None:
    """Target identity, uniqueness, conservation, and positivity are mandatory."""
    with pytest.raises(ValueError, match=message):
        target.validate()


def _valid_plan_inputs() -> dict[str, object]:
    """Build deterministic valid planning inputs."""
    now = datetime(2026, 7, 24, tzinfo=UTC)
    return {
        "idempotency_key": "plan-1",
        "target": _target(),
        "current": PortfolioSnapshot(
            "snapshot-1",
            "account-1",
            now,
            Decimal("10000"),
            {},
        ),
        "prices": {"000001.SZ": Decimal("10")},
        "market_facts": {
            "000001.SZ": {
                "suspended": False,
                "limit_up": False,
                "limit_down": False,
                "volume": 10000,
            }
        },
        "config": {
            "policy_version": "v1",
            "buy_lot_size": 100,
            "fee_rate": "0.001",
            "slippage_rate": "0.001",
            "min_rebalance_value": "0",
            "max_asset_weight": "0.8",
            "max_volume_participation": "0.2",
        },
        "expires_at": now + timedelta(hours=1),
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("policy_version", "", "policy_version"),
        ("buy_lot_size", 0, "buy_lot_size"),
        ("fee_rate", 1, "fee_rate"),
        ("slippage_rate", -0.1, "slippage_rate"),
        ("min_rebalance_value", -1, "min_rebalance"),
        ("max_asset_weight", 0, "max_asset_weight"),
        ("max_volume_participation", 1.1, "max_volume_participation"),
    ],
)
def test_transition_policy_rejects_each_invalid_configuration(
    field: str, value: object, message: str
) -> None:
    """Every planning configuration range fails with an explicit reason."""
    inputs = _valid_plan_inputs()
    config = dict(inputs["config"])  # type: ignore[arg-type]
    config[field] = value
    inputs["config"] = config
    with pytest.raises(ValueError, match=message):
        build_transition_plan(**inputs)  # type: ignore[arg-type]


def test_transition_plan_requires_aware_ordered_times_and_nonnegative_cash() -> None:
    """Snapshot/expiry chronology and account cash fail closed."""
    inputs = _valid_plan_inputs()
    current = inputs["current"]
    assert isinstance(current, PortfolioSnapshot)

    inputs["expires_at"] = current.as_of_time
    with pytest.raises(ValueError, match="expire after"):
        build_transition_plan(**inputs)  # type: ignore[arg-type]

    inputs = _valid_plan_inputs()
    inputs["current"] = PortfolioSnapshot(
        "snapshot-1",
        "account-1",
        datetime(2026, 7, 24),
        Decimal("100"),
        {},
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_transition_plan(**inputs)  # type: ignore[arg-type]

    inputs = _valid_plan_inputs()
    current = inputs["current"]
    assert isinstance(current, PortfolioSnapshot)
    inputs["current"] = PortfolioSnapshot(
        current.snapshot_id,
        current.account_id,
        current.as_of_time,
        Decimal("-1"),
        {},
    )
    with pytest.raises(ValueError, match="cash cannot be negative"):
        build_transition_plan(**inputs)  # type: ignore[arg-type]
