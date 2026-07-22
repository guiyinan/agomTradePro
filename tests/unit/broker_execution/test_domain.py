"""Pure broker execution state and approval rules."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderStatus,
    LiveOrderType,
    OrderApprovalSnapshot,
)
from apps.broker_execution.domain.rules import (
    InvalidOrderTransitionError,
    build_approval_digest,
    is_trading_session_open,
    validate_order_transition,
)


def test_trading_session_rule_rejects_weekends_and_closed_hours() -> None:
    windows = ["09:30-11:30", "13:00-15:00"]
    timezone = ZoneInfo("Asia/Shanghai")

    assert is_trading_session_open(
        datetime(2026, 7, 22, 10, 0, tzinfo=timezone), windows
    )
    assert not is_trading_session_open(
        datetime(2026, 7, 22, 12, 0, tzinfo=timezone), windows
    )
    assert not is_trading_session_open(
        datetime(2026, 7, 25, 10, 0, tzinfo=timezone), windows
    )


def test_state_machine_allows_submit_and_conservative_reconciliation() -> None:
    validate_order_transition(LiveOrderStatus.READY.value, LiveOrderStatus.LEASED.value)
    validate_order_transition(LiveOrderStatus.LEASED.value, LiveOrderStatus.SUBMITTING.value)
    validate_order_transition(
        LiveOrderStatus.SUBMITTING.value,
        LiveOrderStatus.RECONCILIATION_REQUIRED.value,
    )


def test_state_machine_rejects_duplicate_submit_from_ready() -> None:
    with pytest.raises(InvalidOrderTransitionError):
        validate_order_transition(
            LiveOrderStatus.READY.value, LiveOrderStatus.SUBMITTING.value
        )


def test_state_machine_accepts_broker_reported_direct_cancellation() -> None:
    validate_order_transition(
        LiveOrderStatus.SUBMITTED.value, LiveOrderStatus.CANCELED.value
    )
    validate_order_transition(
        LiveOrderStatus.PARTIALLY_FILLED.value, LiveOrderStatus.CANCELED.value
    )
    validate_order_transition(
        LiveOrderStatus.SUBMITTED.value, LiveOrderStatus.BROKER_REJECTED.value
    )


def test_approval_digest_is_stable_and_binds_critical_fields() -> None:
    snapshot = OrderApprovalSnapshot(
        account_id=7,
        asset_code="510300.SH",
        side=LiveOrderSide.BUY,
        order_type=LiveOrderType.LIMIT,
        quantity=Decimal("100"),
        limit_price=Decimal("3.9000"),
        expires_at="2026-07-21T07:00:00+00:00",
        risk_policy_version="risk-v1",
        source_recommendation_ids=("recommendation-1",),
        source_signal_ids=("signal-1",),
    )
    digest = build_approval_digest(snapshot)
    assert digest == build_approval_digest(snapshot)
    assert digest != build_approval_digest(
        OrderApprovalSnapshot(**{**snapshot.__dict__, "quantity": Decimal("200")})
    )
    assert digest != build_approval_digest(
        OrderApprovalSnapshot(
            **{
                **snapshot.__dict__,
                "source_recommendation_ids": ("recommendation-2",),
            }
        )
    )
