"""
Rotation Module Infrastructure Layer - Price Data Adapter

通过 data_center 事实表读取历史价格数据。
"""

import logging
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Literal

from django.utils import timezone

from core.integration.price_history import (
    fetch_close_prices_from_data_center as _fetch_historical_close_prices,
)
from core.integration.price_history import (
    fetch_published_close_prices_from_data_center as fetch_close_prices_from_data_center,
)

PriceReadMode = Literal["published", "historical"]

logger = logging.getLogger(__name__)


class PriceDataCache:
    """Simple cache for price data to reduce API calls"""

    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, tuple[list[float], datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, asset_code: str, end_date: date) -> list[float] | None:
        """Get cached prices if available and not expired"""
        cache_key = f"{asset_code}_{end_date}"

        if cache_key in self._cache:
            prices, cached_at = self._cache[cache_key]
            if timezone.now() - cached_at < self._ttl:
                return prices
            else:
                del self._cache[cache_key]

        return None

    def set(self, asset_code: str, end_date: date, prices: list[float]) -> None:
        """Cache prices"""
        cache_key = f"{asset_code}_{end_date}"
        self._cache[cache_key] = (prices, timezone.now())

    def clear(self) -> None:
        """Clear all cached data"""
        self._cache.clear()


class RotationPriceDataService:
    """
    Rotation 模块价格数据服务。

    从 data_center 事实表读取历史价格。
    """

    def __init__(
        self,
        cache: PriceDataCache | None = None,
    ):
        self.cache = cache or PriceDataCache()

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int = 252,
        *,
        cache_result: bool = True,
        mode: PriceReadMode = "published",
    ) -> list[float] | None:
        """
        获取资产历史收盘价。

        Args:
            asset_code: 资产代码（如 "510300"、"000300"）
            end_date: 截止日期
            days_back: 向前取多少个交易日
            cache_result: 是否把成功读取结果写入进程内缓存

        Returns:
            收盘价列表（从旧到新），或 None
        """
        # 优先查缓存
        if mode not in {"published", "historical"}:
            raise ValueError("mode must be 'published' or 'historical'")

        # Keep historical and decision-facing reads in separate cache
        # namespaces.  A historical replay must never warm the current view.
        cache_asset_code = f"{mode}:{asset_code}"
        cached_prices = self.cache.get(cache_asset_code, end_date)
        if cached_prices and len(cached_prices) >= days_back:
            return cached_prices[-days_back:]

        prices = self._fetch_from_data_center(asset_code, end_date, days_back, mode=mode)

        if prices and cache_result:
            self.cache.set(cache_asset_code, end_date, prices)

        return prices

    def get_multiple_prices(
        self,
        asset_codes: list[str],
        end_date: date,
        days_back: int = 252,
        *,
        mode: PriceReadMode = "published",
    ) -> dict[str, list[float]]:
        """批量获取多个资产的历史价格。"""
        result: dict[str, list[float]] = {}

        for asset_code in asset_codes:
            prices = self.get_prices(asset_code, end_date, days_back, mode=mode)
            if prices:
                result[asset_code] = prices

        return result

    def clear_cache(self) -> None:
        """清除价格缓存"""
        self.cache.clear()

    @staticmethod
    def _fetch_from_data_center(
        asset_code: str,
        end_date: date,
        days_back: int,
        *,
        mode: PriceReadMode = "published",
    ) -> list[float] | None:
        """Read prices using either the current publication or historical port."""
        try:
            if mode == "historical":
                prices = _fetch_historical_close_prices(
                    asset_code=asset_code,
                    end_date=end_date,
                    days_back=days_back,
                )
            else:
                published_payload: object = fetch_close_prices_from_data_center(
                    asset_code=asset_code,
                    end_date=end_date,
                    days_back=days_back,
                )
                if isinstance(published_payload, Mapping):
                    raw_prices: object = published_payload.get("prices")
                else:
                    # Keep the narrow module-level patch seam used by legacy
                    # rotation/factor tests while production returns metadata.
                    raw_prices = published_payload
                if not isinstance(raw_prices, list):
                    return None
                prices = [
                    float(price)
                    for price in raw_prices
                    if not isinstance(price, bool) and isinstance(price, (int, float))
                ]
            if not prices:
                return None
            return prices

        except Exception:
            logger.exception("从 data_center 获取 %s 历史价格失败", asset_code)
            return None
