"""Backtest composite price validation and failover regressions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from typing import cast

import pytest

from apps.backtest.infrastructure.adapters.base import (
    AssetPriceAdapterProtocol,
    AssetPricePoint,
    AssetPriceValidationError,
)
from apps.backtest.infrastructure.adapters.composite_price_adapter import (
    CompositeAssetPriceAdapter,
)


class _PriceAdapter:
    """Small configurable adapter used to exercise failover contracts."""

    def __init__(
        self,
        *,
        source_name: str,
        supported: bool = True,
        price: float | None = None,
        points: list[AssetPricePoint] | None = None,
        supports_error: Exception | None = None,
        price_error: Exception | None = None,
        points_error: Exception | None = None,
    ) -> None:
        self.source_name = source_name
        self.supported = supported
        self.price = price
        self.points = list(points or [])
        self.supports_error = supports_error
        self.price_error = price_error
        self.points_error = points_error
        self.price_calls = 0
        self.points_calls = 0

    def supports(self, asset_class: str) -> bool:
        del asset_class
        if self.supports_error is not None:
            raise self.supports_error
        return self.supported

    def get_price(self, asset_class: str, as_of_date: date) -> float | None:
        del asset_class, as_of_date
        self.price_calls += 1
        if self.price_error is not None:
            raise self.price_error
        return self.price

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date,
    ) -> list[AssetPricePoint]:
        del asset_class, start_date, end_date
        self.points_calls += 1
        if self.points_error is not None:
            raise self.points_error
        return list(self.points)


@pytest.mark.parametrize(
    "invalid_price",
    [True, 0.0, -1.0, float("nan"), float("inf"), float("-inf")],
)
def test_asset_price_point_rejects_non_positive_or_non_finite_prices(
    invalid_price: object,
) -> None:
    """Damaged prices cannot become accepted adapter facts."""

    with pytest.raises(AssetPriceValidationError, match="有限正数|数值类型"):
        AssetPricePoint(
            asset_class="gold",
            price=invalid_price,  # type: ignore[arg-type]
            as_of_date=date(2026, 1, 2),
            source="test",
        )


def test_asset_price_point_is_normalized_immutable_and_date_strict() -> None:
    """Canonical price points detach whitespace and reject datetime subclasses."""

    point = AssetPricePoint(
        asset_class=" gold ",
        price=2,
        as_of_date=date(2026, 1, 2),
        source=" source ",
    )
    assert point.asset_class == "gold"
    assert point.price == 2.0
    assert point.source == "source"
    with pytest.raises(FrozenInstanceError):
        point.price = 3.0  # type: ignore[misc]
    with pytest.raises(AssetPriceValidationError, match="date"):
        AssetPricePoint(
            asset_class="gold",
            price=2.0,
            as_of_date=datetime(2026, 1, 2, tzinfo=UTC),  # type: ignore[arg-type]
            source="test",
        )


def test_default_prices_are_validated_detached_and_only_advertised_when_enabled() -> None:
    """Caller mutation and disabled defaults cannot change support or cached facts."""

    defaults = {"gold": 500.0}
    disabled = CompositeAssetPriceAdapter([], use_defaults=False, default_prices=defaults)
    assert disabled.supports("gold") is False

    enabled = CompositeAssetPriceAdapter([], use_defaults=True, default_prices=defaults)
    defaults["gold"] = float("nan")
    assert enabled.supports("gold") is True
    assert enabled.get_price("gold", date(2026, 1, 2)) == 500.0

    with pytest.raises(ValueError, match="default price"):
        CompositeAssetPriceAdapter([], use_defaults=True, default_prices={"gold": 0.0})


def test_supports_failure_and_secret_bearing_price_error_fail_over(caplog) -> None:
    """One broken source neither blocks fallback nor leaks exception details."""

    broken_support = _PriceAdapter(
        source_name="support-source",
        supports_error=RuntimeError("postgresql://admin:support-secret@example.test/db"),
    )
    broken_price = _PriceAdapter(
        source_name="price-source",
        price_error=RuntimeError("https://user:price-secret@example.test/data"),
    )
    secondary = _PriceAdapter(source_name="secondary", price=501.25)
    adapter = CompositeAssetPriceAdapter(
        cast(
            list[AssetPriceAdapterProtocol],
            [broken_support, broken_price, secondary],
        )
    )

    assert adapter.get_price("gold", date(2026, 1, 2)) == 501.25
    log_text = caplog.text
    assert "support-secret" not in log_text
    assert "price-secret" not in log_text
    assert "RuntimeError" in log_text


@pytest.mark.parametrize("invalid_price", [True, float("nan"), float("inf"), -1.0])
def test_invalid_primary_price_falls_through_to_secondary(invalid_price: object) -> None:
    """Truthy booleans and non-finite values are not cached as market prices."""

    primary = _PriceAdapter(
        source_name="primary",
        price=cast(float, invalid_price),
    )
    secondary = _PriceAdapter(source_name="secondary", price=7.5)
    adapter = CompositeAssetPriceAdapter([primary, secondary])

    assert adapter.get_price("gold", date(2026, 1, 2)) == 7.5
    assert primary.price_calls == 1
    assert secondary.price_calls == 1


def test_series_filters_wrong_asset_and_range_then_sorts_and_deduplicates() -> None:
    """Only canonical target facts survive an external series response."""

    primary = _PriceAdapter(
        source_name="primary",
        points=[
            AssetPricePoint("gold", 4.0, date(2026, 1, 3), "primary"),
            AssetPricePoint("equity", 99.0, date(2026, 1, 2), "primary"),
            AssetPricePoint("gold", 1.0, date(2025, 12, 31), "primary"),
            AssetPricePoint("gold", 2.0, date(2026, 1, 2), "primary"),
            AssetPricePoint("gold", 3.0, date(2026, 1, 2), "primary-revision"),
        ],
    )
    adapter = CompositeAssetPriceAdapter([primary])

    points = adapter.get_prices("gold", date(2026, 1, 1), date(2026, 1, 3))

    assert [(point.as_of_date, point.price) for point in points] == [
        (date(2026, 1, 2), 3.0),
        (date(2026, 1, 3), 4.0),
    ]


def test_invalid_series_payload_fails_over_and_dates_validate_before_io() -> None:
    """Dynamic series shapes and reversed dates cannot reach downstream consumers."""

    primary = _PriceAdapter(source_name="primary")
    primary.points = cast(list[AssetPricePoint], [object()])
    secondary = _PriceAdapter(
        source_name="secondary",
        points=[AssetPricePoint("gold", 8.0, date(2026, 1, 2), "secondary")],
    )
    adapter = CompositeAssetPriceAdapter([primary, secondary])
    assert adapter.get_prices("gold", date(2026, 1, 1), date(2026, 1, 3)) == secondary.points

    with pytest.raises(ValueError, match="start_date"):
        adapter.get_prices("gold", date(2026, 1, 3), date(2026, 1, 1))
    assert primary.points_calls == 1
    assert secondary.points_calls == 1
