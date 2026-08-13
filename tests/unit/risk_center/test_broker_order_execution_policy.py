from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.risk_center.domain.broker_order_execution_policy import (
    BrokerOrderExecutionRiskControls,
    BrokerOrderExecutionRiskPolicy,
    validate_broker_order_execution_policy_successor,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)


def _controls(**changes: object) -> BrokerOrderExecutionRiskControls:
    values: dict[str, object] = {
        "max_total_position_pct": Decimal("0.8"),
        "max_single_position_pct": Decimal("0.18"),
        "max_daily_loss_pct": Decimal("0.035"),
        "max_drawdown_pct": Decimal("0.12"),
        "max_stop_loss_pct": Decimal("0.1"),
        "take_profit_pct": Decimal("0.25"),
        "min_cash_pct": Decimal("0.15"),
        "force_stop_loss": True,
        "hard_exclusions": ("000001.SZ", "600000.SH"),
    }
    values.update(changes)
    return BrokerOrderExecutionRiskControls(**values)  # type: ignore[arg-type]


def _policy(**changes: object) -> BrokerOrderExecutionRiskPolicy:
    values: dict[str, object] = {
        "policy_id": "broker-order-policy:7",
        "policy_version": "v1",
        "account_id": 7,
        "controls": _controls(),
        "source_snapshot_id": "risk-source-snapshot:7:v1",
        "source_snapshot_version": "v1",
        "source_snapshot_hash": "a" * 64,
        "recorded_at": NOW,
        "activated_at": NOW + timedelta(minutes=1),
        "valid_until": NOW + timedelta(days=1),
    }
    values.update(changes)
    return BrokerOrderExecutionRiskPolicy(**values)  # type: ignore[arg-type]


def test_policy_is_content_addressed_and_has_strict_pit_boundaries() -> None:
    policy = _policy()
    assert len(policy.content_hash) == 64
    assert not policy.is_active_at(policy.recorded_at)
    assert policy.is_active_at(policy.activated_at)
    assert not policy.is_active_at(policy.valid_until)
    assert policy.to_payload()["permission_cap"] == "execution_eligible"


def test_decimal_and_timezone_equivalence_are_canonical() -> None:
    first = _policy(controls=_controls(max_total_position_pct=Decimal("0.80")))
    second = _policy(
        controls=_controls(max_total_position_pct=Decimal("0.8")),
        activated_at=(NOW + timedelta(minutes=1)).astimezone(timezone(timedelta(hours=8))),
    )
    assert first.content_hash == second.content_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"max_total_position_pct": Decimal("NaN")},
        {"max_single_position_pct": Decimal("1.1")},
        {"force_stop_loss": 1},
        {"hard_exclusions": ("600000.SH", "000001.SZ")},
        {"hard_exclusions": ("600000.SH", "600000.SH")},
    ],
)
def test_controls_fail_closed_on_noncanonical_or_unsafe_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _controls(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": True},
        {"source_snapshot_hash": "A" * 64},
        {"recorded_at": datetime(2026, 8, 13, 8)},
        {"activated_at": NOW - timedelta(seconds=1)},
        {"permission_cap": "display_only"},
        {"content_hash": "b" * 64},
    ],
)
def test_policy_fails_closed_on_identity_clock_permission_or_hash_tamper(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _policy(**changes)


def test_each_source_or_control_change_changes_policy_hash() -> None:
    original = _policy()
    assert _policy(source_snapshot_hash="b" * 64).content_hash != original.content_hash
    assert _policy(controls=_controls(min_cash_pct=Decimal("0.16"))).content_hash != (
        original.content_hash
    )


def test_successor_binds_exact_predecessor_account_and_advanced_clock() -> None:
    previous = _policy()
    successor = _policy(
        policy_version="v2",
        recorded_at=NOW + timedelta(hours=1),
        activated_at=NOW + timedelta(hours=1),
        supersedes_policy_hash=previous.content_hash,
    )
    validate_broker_order_execution_policy_successor(previous, successor)
    with pytest.raises(ValueError, match="exact previous"):
        validate_broker_order_execution_policy_successor(
            previous,
            replace(successor, supersedes_policy_hash="b" * 64, content_hash=""),
        )
