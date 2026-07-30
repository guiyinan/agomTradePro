"""Durable alert and price-update boundaries for Realtime."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.realtime.domain.entities import (
    AlertCondition,
    AlertStatus,
    AssetType,
    PriceAlert,
    PricePollingConfig,
    PriceSnapshot,
    PriceSubscription,
    PriceUpdate,
    PriceUpdateStatus,
    RealtimePrice,
    normalize_asset_code,
)
from apps.realtime.domain.rules import (
    calculate_change_pct,
    classify_price_update,
    should_trigger_alert,
)
from apps.realtime.domain.services import build_price_update


@pytest.mark.parametrize("value", ["", " ", "A" * 33])
def test_asset_code_rejects_empty_or_oversized_values(value: str) -> None:
    """Realtime identifiers remain bounded at ingestion."""
    with pytest.raises(ValueError, match="asset_code"):
        normalize_asset_code(value)
    assert normalize_asset_code(" 000001.sz ") == "000001.SZ"


def test_price_alert_validates_owner_threshold_message_and_status() -> None:
    """Alerts reject invalid ownership/economics and inactive alerts never fire."""
    with pytest.raises(ValueError, match="owner_id"):
        PriceAlert(0, "000001.SZ", AlertCondition.ABOVE, Decimal("10"))
    with pytest.raises(ValueError, match="threshold"):
        PriceAlert(1, "000001.SZ", AlertCondition.ABOVE, Decimal("0"))
    with pytest.raises(ValueError, match="message"):
        PriceAlert(
            1,
            "000001.SZ",
            AlertCondition.ABOVE,
            Decimal("10"),
            message="x" * 501,
        )

    inactive = PriceAlert(
        1,
        "000001.SZ",
        AlertCondition.ABOVE,
        Decimal("10"),
        status=AlertStatus.INACTIVE,
    )
    assert inactive.is_triggered_by(Decimal("9"), Decimal("11")) is False
    with pytest.raises(ValueError, match="owner_id"):
        PriceSubscription(0, "000001.SZ")


@pytest.mark.parametrize(
    ("condition", "old", "new", "expected"),
    [
        (AlertCondition.ABOVE, None, Decimal("10"), True),
        (AlertCondition.BELOW, None, Decimal("10"), True),
        (AlertCondition.CROSS_UP, None, Decimal("11"), False),
        (AlertCondition.CROSS_UP, Decimal("9"), Decimal("10"), True),
        (AlertCondition.CROSS_UP, Decimal("10"), Decimal("11"), False),
        (AlertCondition.CROSS_DOWN, Decimal("11"), Decimal("10"), True),
        (AlertCondition.CROSS_DOWN, Decimal("10"), Decimal("9"), False),
    ],
)
def test_alert_conditions_have_exact_crossing_semantics(
    condition: AlertCondition,
    old: Decimal | None,
    new: Decimal,
    expected: bool,
) -> None:
    """Cross alerts require movement from the opposite side of the threshold."""
    assert should_trigger_alert(condition, Decimal("10"), old, new) is expected


@pytest.mark.parametrize(
    ("old", "new", "status"),
    [
        (None, None, PriceUpdateStatus.FAILED),
        (None, Decimal("10"), PriceUpdateStatus.SUCCESS),
        (Decimal("10"), Decimal("10"), PriceUpdateStatus.NO_CHANGE),
        (Decimal("10"), Decimal("11"), PriceUpdateStatus.SUCCESS),
    ],
)
def test_price_update_classification(
    old: Decimal | None,
    new: Decimal | None,
    status: PriceUpdateStatus,
) -> None:
    """Missing, initial, unchanged, and changed quotes are distinct."""
    assert classify_price_update(old, new) == status


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (None, Decimal("10"), None),
        (Decimal("10"), None, None),
        (Decimal("0"), Decimal("10"), None),
        (Decimal("10"), Decimal("11"), Decimal("10")),
    ],
)
def test_change_percentage_is_decimal_safe(
    old: Decimal | None,
    new: Decimal | None,
    expected: Decimal | None,
) -> None:
    """Percentage calculation avoids division by zero and float conversion."""
    assert calculate_change_pct(old, new) == expected


def test_price_value_objects_serialize_missing_and_present_values() -> None:
    """Realtime API payloads preserve timestamps and optional quote fields."""
    timestamp = datetime(2026, 7, 24, tzinfo=UTC)
    price = RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("10"),
        change=None,
        change_pct=None,
        volume=100,
        timestamp=timestamp,
        source="fake",
    )
    assert price.to_dict()["change"] is None

    update = PriceUpdate(
        asset_code="000001.SZ",
        old_price=Decimal("10"),
        new_price=Decimal("11"),
        status=PriceUpdateStatus.SUCCESS,
        timestamp=timestamp,
    )
    assert update.price_changed is True
    assert update.price_change == Decimal("1")
    assert update.price_change_pct == Decimal("10")
    assert update.to_dict()["new_price"] == 11.0

    missing = PriceUpdate(
        asset_code="000001.SZ",
        old_price=None,
        new_price=None,
        status=PriceUpdateStatus.FAILED,
        timestamp=timestamp,
    )
    assert missing.price_changed is False
    assert missing.price_change is None
    assert missing.price_change_pct is None
    assert missing.to_dict()["old_price"] is None

    zero = PriceUpdate(
        asset_code="000001.SZ",
        old_price=Decimal("0"),
        new_price=Decimal("1"),
        status=PriceUpdateStatus.SUCCESS,
        timestamp=timestamp,
    )
    assert zero.price_change_pct is None


def test_realtime_price_freshness_rejects_old_future_and_naive_timestamps() -> None:
    """Realtime quotes are usable only inside a bounded aware observation window."""

    observed_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    reference_time = observed_at + timedelta(minutes=5)

    def _price(timestamp: datetime) -> RealtimePrice:
        return RealtimePrice(
            asset_code="000001.SH",
            asset_type=AssetType.INDEX,
            price=Decimal("3800"),
            change=None,
            change_pct=None,
            volume=100,
            timestamp=timestamp,
            source="test",
        )

    assert _price(observed_at).is_fresh(
        reference_time=reference_time,
        max_age=timedelta(minutes=5),
    )
    assert not _price(observed_at - timedelta(seconds=1)).is_fresh(
        reference_time=reference_time,
        max_age=timedelta(minutes=5),
    )
    assert not _price(reference_time + timedelta(seconds=1)).is_fresh(
        reference_time=reference_time,
        max_age=timedelta(minutes=5),
    )
    assert not _price(datetime(2026, 7, 30, 10, 0)).is_fresh(
        reference_time=reference_time,
        max_age=timedelta(minutes=5),
    )


def test_price_update_service_overrides_status_on_explicit_error() -> None:
    """Adapter errors fail the update even when a new price is present."""
    timestamp = datetime(2026, 7, 24, tzinfo=UTC)
    update = build_price_update(
        asset_code="000001.SZ",
        old_price=Decimal("10"),
        new_price=Decimal("11"),
        timestamp=timestamp,
        error_message="source mismatch",
    )
    assert update.status == PriceUpdateStatus.FAILED
    assert update.error_message == "source mismatch"

    unchanged = build_price_update(
        asset_code="000001.SZ",
        old_price=Decimal("10"),
        new_price=Decimal("10"),
        timestamp=timestamp,
    )
    assert unchanged.status == PriceUpdateStatus.NO_CHANGE


def test_polling_and_snapshot_contracts_cover_empty_and_success_cases() -> None:
    """Batch quote summaries expose stable success rates."""
    timestamp = datetime(2026, 7, 24, tzinfo=UTC)
    assert PricePollingConfig().to_dict()["batch_size"] == 100
    empty = PriceSnapshot(timestamp, [], 0, 0, 0)
    assert empty.success_rate == 0.0
    assert empty.to_dict()["prices"] == []

    price = RealtimePrice(
        "000001.SZ",
        AssetType.EQUITY,
        Decimal("10"),
        Decimal("1"),
        Decimal("11.11"),
        100,
        timestamp,
        "fake",
    )
    snapshot = PriceSnapshot(timestamp, [price], 2, 1, 1)
    assert snapshot.success_rate == 0.5
    assert snapshot.to_dict()["prices"][0]["asset_code"] == "000001.SZ"
