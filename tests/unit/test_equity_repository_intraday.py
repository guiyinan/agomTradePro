import sys
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from django.utils import timezone

from apps.equity.domain.entities import IntradayPricePoint
from apps.equity.infrastructure.repositories import DjangoStockRepository
from core.exceptions import DataFetchError, DataValidationError


def _point(
    hour: int,
    minute: int,
    price: str,
    avg_price: str | None = None,
    volume: int | None = 1000,
) -> IntradayPricePoint:
    return IntradayPricePoint(
        stock_code="000001.SZ",
        timestamp=datetime(2026, 4, 3, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai")),
        price=Decimal(price),
        avg_price=Decimal(avg_price) if avg_price is not None else None,
        volume=volume,
    )


def test_get_intraday_points_uses_primary_source_and_tracks_source(monkeypatch):
    repository = DjangoStockRepository()
    primary_points = [_point(9, 30, "10.01", "10.00"), _point(9, 31, "10.02", "10.01")]

    monkeypatch.setattr(
        repository,
        "_get_intraday_hist_min_points",
        lambda stock_code, symbol: primary_points,
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_tick_points",
        lambda stock_code, symbol: (_ for _ in ()).throw(AssertionError("fallback should not be used")),
    )

    points = repository.get_intraday_points("000001.SZ")

    assert points == primary_points
    assert repository.get_last_intraday_source() == "akshare_hist_min_em"


def test_get_intraday_points_skips_stale_sparse_quote_snapshots(monkeypatch):
    repository = DjangoStockRepository()
    stale_time = timezone.now() - timedelta(days=14)
    repository._dc_quote_repo = SimpleNamespace(
        get_series=lambda stock_code, limit: [
            SimpleNamespace(
                snapshot_at=stale_time,
                current_price=Decimal("10.00"),
                volume=1000,
            ),
            SimpleNamespace(
                snapshot_at=stale_time + timedelta(minutes=1),
                current_price=Decimal("10.01"),
                volume=1000,
            ),
        ]
    )
    primary_points = [_point(9, 30, "10.01", "10.00"), _point(9, 31, "10.02", "10.01")]

    monkeypatch.setattr(
        repository,
        "_get_intraday_hist_min_points",
        lambda stock_code, symbol: primary_points,
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_tick_points",
        lambda stock_code, symbol: (_ for _ in ()).throw(AssertionError("fallback should not be used")),
    )

    points = repository.get_intraday_points("000001.SZ")

    assert points == primary_points
    assert repository.get_last_intraday_source() == "akshare_hist_min_em"


def test_get_intraday_points_uses_validated_fallback_when_primary_fails(monkeypatch):
    repository = DjangoStockRepository()
    fallback_points = [_point(9, 30, "10.00", "10.00"), _point(9, 31, "10.02", "10.01")]

    def raise_primary_error(stock_code: str, symbol: str) -> list[IntradayPricePoint]:
        raise DataFetchError(message="primary failed")

    monkeypatch.setattr(repository, "_get_intraday_hist_min_points", raise_primary_error)
    monkeypatch.setattr(
        repository,
        "_get_intraday_tick_points",
        lambda stock_code, symbol: fallback_points,
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_validation_price",
        lambda stock_code: Decimal("10.01"),
    )

    points = repository.get_intraday_points("000001.SZ")

    assert points == fallback_points
    assert repository.get_last_intraday_source() == "akshare_intraday_em_fallback"


def test_get_intraday_points_rejects_unvalidated_fallback_when_primary_is_empty(monkeypatch):
    repository = DjangoStockRepository()

    monkeypatch.setattr(repository, "_get_intraday_hist_min_points", lambda stock_code, symbol: [])
    monkeypatch.setattr(
        repository,
        "_get_intraday_tick_points",
        lambda stock_code, symbol: [_point(9, 30, "10.01", "10.00")],
    )

    with pytest.raises(DataFetchError, match="拒绝切换到未校验备用源"):
        repository.get_intraday_points("000001.SZ")


def test_get_intraday_points_rejects_fallback_with_large_validation_gap(monkeypatch):
    repository = DjangoStockRepository()
    fallback_points = [_point(9, 30, "10.00", "10.00"), _point(9, 31, "10.30", "10.10")]

    monkeypatch.setattr(
        repository,
        "_get_intraday_hist_min_points",
        lambda stock_code, symbol: (_ for _ in ()).throw(DataFetchError(message="primary failed")),
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_tick_points",
        lambda stock_code, symbol: fallback_points,
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_validation_price",
        lambda stock_code: Decimal("10.00"),
    )

    with pytest.raises(DataValidationError, match="校验失败"):
        repository.get_intraday_points("000001.SZ")


def test_hist_min_points_are_timezone_aware(monkeypatch):
    repository = DjangoStockRepository()
    fake_akshare = SimpleNamespace(
        stock_zh_a_hist_min_em=lambda symbol, period, adjust: pd.DataFrame(
            {
                "时间": ["2026-04-03 09:30:00", "2026-04-03 09:31:00"],
                "收盘": ["10.00", "10.02"],
                "均价": ["9.99", "10.01"],
                "成交量": [1000, 2000],
            }
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    points = repository._get_intraday_hist_min_points("000001.SZ", "000001")

    assert len(points) == 2
    assert timezone.is_aware(points[0].timestamp)
    assert points[0].timestamp.tzinfo == ZoneInfo("Asia/Shanghai")


def test_tick_points_are_timezone_aware(monkeypatch):
    repository = DjangoStockRepository()
    fake_akshare = SimpleNamespace(
        stock_intraday_em=lambda symbol: pd.DataFrame(
            {
                "时间": ["09:30:00", "09:30:30", "09:31:00"],
                "成交价": ["10.00", "10.05", "10.06"],
                "手数": [10, 20, 30],
            }
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    points = repository._get_intraday_tick_points("000001.SZ", "000001")

    assert len(points) == 2
    assert timezone.is_aware(points[0].timestamp)
    assert points[0].timestamp.tzinfo == ZoneInfo("Asia/Shanghai")
