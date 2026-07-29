"""Boundary regressions for the legacy Tushare price adapter."""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import pytest
from django.db import DatabaseError

from apps.backtest.infrastructure.adapters import tushare_price_adapter
from apps.backtest.infrastructure.adapters.tushare_price_adapter import (
    TushareAssetPriceAdapter,
)


class _Bars:
    def __init__(self, result: list[object] | None = None, error: Exception | None = None) -> None:
        self.result = result or []
        self.error = error
        self.calls = 0

    def get_bars(self, *_: object, **__: object) -> list[object]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def test_adapter_does_not_retain_legacy_credentials() -> None:
    """Unused compatibility credentials do not remain reachable on the adapter."""

    adapter = TushareAssetPriceAdapter(token="top-secret", http_url="https://internal")

    assert not hasattr(adapter, "_token")
    assert not hasattr(adapter, "_http_url")


def test_price_lookup_redacts_database_exception(monkeypatch, caplog) -> None:
    """Repository failures return no price without logging credential-bearing text."""

    secret = "postgresql://user:secret@internal/backtest"
    adapter = TushareAssetPriceAdapter()
    adapter._bars = _Bars(error=DatabaseError(secret))
    monkeypatch.setattr(
        tushare_price_adapter,
        "get_tushare_asset_tickers",
        lambda: {"equity": "510300.SH"},
    )

    with caplog.at_level(logging.WARNING, logger=tushare_price_adapter.__name__):
        result = adapter.get_price("equity", date(2026, 7, 29))

    assert result is None
    assert "secret" not in caplog.text
    assert "DatabaseError" in caplog.text


def test_price_history_rejects_reverse_range_before_repository() -> None:
    """An invalid date range cannot reach the persistence boundary."""

    adapter = TushareAssetPriceAdapter()
    bars = _Bars()
    adapter._bars = bars

    with pytest.raises(ValueError, match="start_date"):
        adapter.get_prices("cash", date(2026, 7, 30), date(2026, 7, 29))

    assert bars.calls == 0


def test_price_history_skips_invalid_dynamic_rows(monkeypatch) -> None:
    """Malformed repository rows cannot contaminate the returned price series."""

    adapter = TushareAssetPriceAdapter()
    adapter._bars = _Bars(
        result=[
            SimpleNamespace(
                close=10.5,
                bar_date=date(2026, 7, 29),
                source="valid-source",
            ),
            SimpleNamespace(
                close=float("nan"),
                bar_date=date(2026, 7, 28),
                source="invalid-source",
            ),
        ]
    )
    monkeypatch.setattr(
        tushare_price_adapter,
        "get_tushare_asset_tickers",
        lambda: {"equity": "510300.SH"},
    )

    result = adapter.get_prices("equity", date(2026, 7, 28), date(2026, 7, 29))

    assert [(point.as_of_date, point.price) for point in result] == [(date(2026, 7, 29), 10.5)]
