"""T5 failover contracts for composite and data-center price adapters."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.backtest.infrastructure.adapters import composite_price_adapter as composite
from apps.backtest.infrastructure.adapters.base import (
    AssetPricePoint,
    AssetPriceUnavailableError,
)
from apps.backtest.infrastructure.adapters.composite_price_adapter import (
    CompositeAssetPriceAdapter,
    DataCenterAssetPriceAdapter,
)


class _PriceAdapter:
    """Configurable protocol-compatible adapter double."""

    def __init__(
        self,
        *,
        name: str,
        supported: bool = True,
        price: float | None = None,
        points: list[AssetPricePoint] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.source_name = name
        self.supported = supported
        self.price = price
        self.points = points or []
        self.error = error

    def supports(self, _asset_class: str) -> bool:
        return self.supported

    def get_price(self, _asset_class: str, _as_of_date: date) -> float | None:
        if self.error:
            raise self.error
        return self.price

    def get_prices(
        self,
        _asset_class: str,
        _start_date: date,
        _end_date: date,
    ) -> list[AssetPricePoint]:
        if self.error:
            raise self.error
        return self.points


def test_composite_price_failover_cache_defaults_and_errors() -> None:
    """Single-price lookup must skip unsupported/invalid sources and cache success."""
    trade_date = date(2026, 7, 25)
    unsupported = _PriceAdapter(name="unsupported", supported=False)
    broken = _PriceAdapter(name="broken", error=RuntimeError("offline"))
    invalid = _PriceAdapter(name="invalid", price=0)
    healthy = _PriceAdapter(name="healthy", price=12.5)
    adapter = CompositeAssetPriceAdapter(
        [unsupported, broken, invalid, healthy],
        default_prices={"gold": 99},
    )
    assert adapter.supports("gold") is True
    assert adapter.supports("equity") is True
    assert adapter.get_price("cash", trade_date) == 1.0
    assert adapter.get_price("equity", trade_date) == 12.5
    healthy.price = 20
    assert adapter.get_price("equity", trade_date) == 12.5
    assert adapter.get_price("equity", trade_date, use_cache=False) == 20
    adapter.clear_cache()

    defaults = CompositeAssetPriceAdapter(
        [broken],
        use_defaults=True,
        default_prices={"gold": 99},
    )
    assert defaults.get_price("gold", trade_date) == 99

    failing = CompositeAssetPriceAdapter([broken])
    with pytest.raises(AssetPriceUnavailableError):
        failing.get_price("gold", trade_date)
    assert CompositeAssetPriceAdapter([unsupported]).get_price("gold", trade_date) is None


def test_composite_price_series_failover_and_default_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Series lookup must return first data, isolate errors, or build explicit defaults."""
    start = date(2026, 7, 24)
    end = date(2026, 7, 25)
    point = AssetPricePoint("gold", 100, start, "healthy")
    adapter = CompositeAssetPriceAdapter(
        [
            _PriceAdapter(name="skip", supported=False),
            _PriceAdapter(name="broken", error=RuntimeError("offline")),
            _PriceAdapter(name="empty"),
            _PriceAdapter(name="healthy", points=[point]),
        ]
    )
    assert adapter.get_prices("gold", start, end) == [point]

    defaults = CompositeAssetPriceAdapter(
        [],
        use_defaults=True,
        default_prices={"gold": 88},
    )
    points = defaults.get_prices("gold", start, end)
    assert [(item.as_of_date, item.price, item.source) for item in points] == [
        (start, 88, "default"),
        (end, 88, "default"),
    ]
    assert CompositeAssetPriceAdapter([]).get_prices("gold", start, end) == []

    monkeypatch.setattr(
        composite,
        "get_asset_class_tickers",
        lambda: {"equity": "000300.SH", "gold": "AU"},
    )
    assert set(adapter.get_supported_assets()) == {"equity", "gold"}


def test_data_center_adapter_cash_ticker_bars_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Data-center adapter must normalize cash, configured tickers, and bar order."""
    monkeypatch.setattr(
        composite,
        "get_asset_class_tickers",
        lambda: {"equity": "000300.SH"},
    )
    adapter = DataCenterAssetPriceAdapter.__new__(DataCenterAssetPriceAdapter)
    adapter._price_service = MagicMock()
    adapter._price_service.get_price.return_value = 12.5
    adapter._bars = MagicMock()
    adapter._bars.get_bars.return_value = [
        SimpleNamespace(
            close=12,
            bar_date=date(2026, 7, 25),
            source="provider",
        ),
        SimpleNamespace(
            close=11,
            bar_date=date(2026, 7, 24),
            source="",
        ),
    ]

    assert adapter.supports("cash") is True
    assert adapter.supports("equity") is True
    assert adapter.supports("unknown") is False
    assert adapter.get_price("cash", date.today()) == 1.0
    assert adapter.get_price("unknown", date.today()) is None
    assert adapter.get_price("equity", date.today()) == 12.5

    cash = adapter.get_prices("cash", date(2026, 7, 24), date(2026, 7, 25))
    assert len(cash) == 2
    assert adapter.get_prices("unknown", date.today(), date.today()) == []
    bars = adapter.get_prices("equity", date(2026, 7, 24), date(2026, 7, 25))
    assert [item.price for item in bars] == [11, 12]
    assert bars[0].source == "data_center"

    adapter._bars.get_bars.side_effect = RuntimeError("offline")
    assert adapter.get_prices("equity", date.today(), date.today()) == []


def test_default_adapter_factory_isolates_optional_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default composition must retain healthy providers and skip initialization failures."""
    data_center = MagicMock()
    tushare = MagicMock()
    monkeypatch.setattr(composite, "DataCenterAssetPriceAdapter", lambda: data_center)
    monkeypatch.setattr(
        "apps.backtest.infrastructure.adapters.tushare_price_adapter.TushareAssetPriceAdapter",
        MagicMock(return_value=tushare),
    )
    created = composite.create_default_price_adapter("token", "https://example.test")
    assert created._adapters == [data_center, tushare]

    monkeypatch.setattr(
        composite,
        "DataCenterAssetPriceAdapter",
        MagicMock(side_effect=RuntimeError("data center offline")),
    )
    monkeypatch.setattr(
        "apps.backtest.infrastructure.adapters.tushare_price_adapter.TushareAssetPriceAdapter",
        MagicMock(side_effect=RuntimeError("tushare offline")),
    )
    empty = composite.create_default_price_adapter("token")
    assert empty._adapters == []
    assert composite.create_default_price_adapter()._adapters == []
