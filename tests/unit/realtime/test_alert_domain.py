"""Domain contracts for realtime alerts and subscriptions."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.realtime.domain.entities import (
    AlertCondition,
    AlertStatus,
    PriceAlert,
    PriceSubscription,
)
from apps.realtime.domain.rules import should_trigger_alert


@pytest.mark.parametrize(
    ("condition", "old_price", "new_price", "expected"),
    [
        (AlertCondition.ABOVE, None, Decimal("10.00"), True),
        (AlertCondition.ABOVE, Decimal("9.99"), Decimal("9.999999"), False),
        (AlertCondition.BELOW, None, Decimal("10.00"), True),
        (AlertCondition.BELOW, Decimal("10.01"), Decimal("10.000001"), False),
        (AlertCondition.CROSS_UP, Decimal("9.99"), Decimal("10.00"), True),
        (AlertCondition.CROSS_UP, Decimal("10.00"), Decimal("10.01"), False),
        (AlertCondition.CROSS_UP, None, Decimal("10.01"), False),
        (AlertCondition.CROSS_DOWN, Decimal("10.01"), Decimal("10.00"), True),
        (AlertCondition.CROSS_DOWN, Decimal("10.00"), Decimal("9.99"), False),
        (AlertCondition.CROSS_DOWN, None, Decimal("9.99"), False),
    ],
)
def test_should_trigger_alert_boundaries(
    condition: AlertCondition,
    old_price: Decimal | None,
    new_price: Decimal,
    expected: bool,
) -> None:
    assert (
        should_trigger_alert(condition, Decimal("10.00"), old_price, new_price)
        is expected
    )


def test_alert_and_subscription_normalize_asset_codes() -> None:
    alert = PriceAlert(
        owner_id=7,
        asset_code=" 510300.sh ",
        condition=AlertCondition.ABOVE,
        threshold=Decimal("3.123456"),
    )
    subscription = PriceSubscription(owner_id=7, asset_code=" 510300.sh ")

    assert alert.asset_code == "510300.SH"
    assert subscription.asset_code == "510300.SH"
    assert alert.threshold == Decimal("3.123456")


@pytest.mark.parametrize("threshold", [Decimal("0"), Decimal("-0.01")])
def test_alert_rejects_non_positive_threshold(threshold: Decimal) -> None:
    with pytest.raises(ValueError, match="positive"):
        PriceAlert(
            owner_id=7,
            asset_code="510300.SH",
            condition=AlertCondition.ABOVE,
            threshold=threshold,
        )


@pytest.mark.parametrize("asset_code", ["", " ", "A" * 33])
def test_realtime_values_reject_invalid_asset_codes(asset_code: str) -> None:
    with pytest.raises(ValueError, match="asset_code"):
        PriceSubscription(owner_id=7, asset_code=asset_code)


def test_inactive_and_triggered_alerts_do_not_repeat() -> None:
    now = datetime.now(UTC)
    inactive = PriceAlert(
        id=1,
        owner_id=7,
        asset_code="510300.SH",
        condition=AlertCondition.ABOVE,
        threshold=Decimal("3"),
        status=AlertStatus.INACTIVE,
    )
    triggered = PriceAlert(
        id=2,
        owner_id=7,
        asset_code="510300.SH",
        condition=AlertCondition.CROSS_UP,
        threshold=Decimal("3"),
        status=AlertStatus.TRIGGERED,
        triggered_price=Decimal("3.1"),
        triggered_at=now,
    )

    assert inactive.is_triggered_by(Decimal("2.9"), Decimal("3.1")) is False
    assert triggered.is_triggered_by(Decimal("2.9"), Decimal("3.1")) is False
