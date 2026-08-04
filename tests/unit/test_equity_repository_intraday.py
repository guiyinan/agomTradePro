import sys
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from django.utils import timezone

from apps.equity.domain.entities import IntradayPricePoint
from apps.equity.infrastructure.repositories import DjangoStockRepository
from apps.realtime.domain.entities import AssetType, PricePollingConfig, RealtimePrice
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
        lambda stock_code, symbol: (_ for _ in ()).throw(
            AssertionError("fallback should not be used")
        ),
    )

    points = repository.get_intraday_points("000001.SZ")

    assert points == primary_points
    assert repository.get_last_intraday_source() == "akshare_hist_min_em"


def test_get_intraday_points_prefers_local_quote_snapshots_before_remote(monkeypatch):
    repository = DjangoStockRepository()
    market_tz = ZoneInfo("Asia/Shanghai")
    session_start = (
        timezone.now().astimezone(market_tz).replace(hour=9, minute=30, second=0, microsecond=0)
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.intraday_repository.get_published_quote_series",
        lambda _stock_code, publication_key="current", limit=600: {
            "rows": [
                {
                    "snapshot_at": session_start.isoformat(),
                    "current_price": "10.00",
                    "volume": 1000,
                },
                {
                    "snapshot_at": (session_start + timedelta(minutes=1)).isoformat(),
                    "current_price": "10.02",
                    "volume": 1500,
                },
                {
                    "snapshot_at": (session_start + timedelta(minutes=2)).isoformat(),
                    "current_price": "10.03",
                    "volume": 1800,
                },
            ],
            "must_not_use_for_decision": False,
            "publication_id": "pub-quote",
        },
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_hist_min_points",
        lambda stock_code, symbol: (_ for _ in ()).throw(
            AssertionError("primary should not be used")
        ),
    )
    monkeypatch.setattr(
        repository,
        "_get_intraday_tick_points",
        lambda stock_code, symbol: (_ for _ in ()).throw(
            AssertionError("fallback should not be used")
        ),
    )

    points = repository.get_intraday_points("000001.SZ")

    assert len(points) == 3
    assert points[-1].price == Decimal("10.03")
    assert repository.get_last_intraday_source() == "data_center_published_quote_snapshot"


def test_get_intraday_points_skips_stale_sparse_quote_snapshots(monkeypatch):
    repository = DjangoStockRepository()
    stale_time = timezone.now() - timedelta(days=14)
    monkeypatch.setattr(
        "apps.equity.infrastructure.intraday_repository.get_published_quote_series",
        lambda _stock_code, publication_key="current", limit=600: {
            "rows": [
                {
                    "snapshot_at": stale_time.isoformat(),
                    "current_price": "10.00",
                    "volume": 1000,
                },
                {
                    "snapshot_at": (stale_time + timedelta(minutes=1)).isoformat(),
                    "current_price": "10.01",
                    "volume": 1000,
                },
            ],
            "must_not_use_for_decision": False,
            "publication_id": "pub-quote",
        },
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
        lambda stock_code, symbol: (_ for _ in ()).throw(
            AssertionError("fallback should not be used")
        ),
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


def test_intraday_validation_price_skips_stale_cache_and_uses_live_provider():
    """过期 Redis 行情不能成为备用分时源的一致性校验基准。"""
    repository = DjangoStockRepository()
    now = timezone.now()
    max_age = PricePollingConfig().max_price_age_seconds
    stale_cached_price = RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("9.50"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=now - timedelta(seconds=max_age + 1),
        source="redis",
    )
    live_provider_price = RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("10.01"),
        change=None,
        change_pct=None,
        volume=2000,
        timestamp=now,
        source="akshare",
    )

    with (
        patch(
            "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
        ) as cache_repository_class,
        patch(
            "apps.realtime.infrastructure.repositories.AKSharePriceDataProvider"
        ) as live_provider_class,
    ):
        cache_repository_class.return_value.get_latest_price.return_value = stale_cached_price
        live_provider_class.return_value.get_realtime_price.return_value = live_provider_price

        result = repository._get_intraday_validation_price("000001.SZ")

    assert result == Decimal("10.01")
    live_provider_class.return_value.get_realtime_price.assert_called_once_with("000001.SZ")


def test_intraday_validation_price_uses_fresh_cache_without_remote_call():
    """新鲜 Redis 行情仍可作为一致性校验基准，避免不必要的远端调用。"""
    repository = DjangoStockRepository()
    cached_price = RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("10.00"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=timezone.now(),
        source="redis",
    )

    with (
        patch(
            "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
        ) as cache_repository_class,
        patch(
            "apps.realtime.infrastructure.repositories.AKSharePriceDataProvider"
        ) as live_provider_class,
    ):
        cache_repository_class.return_value.get_latest_price.return_value = cached_price

        result = repository._get_intraday_validation_price("000001.SZ")

    assert result == Decimal("10.00")
    live_provider_class.assert_not_called()


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
