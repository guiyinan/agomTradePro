"""
Rotation Module Infrastructure Layer - Price Data Adapter

通过 data_center 事实表读取历史价格数据。
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from django.utils import timezone
from core.integration.price_history import fetch_close_prices_from_data_center

logger = logging.getLogger(__name__)


class PriceDataCache:
    """Simple cache for price data to reduce API calls"""

    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, tuple[list[float], datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(
        self,
        asset_code: str,
        end_date: date
    ) -> list[float] | None:
        """Get cached prices if available and not expired"""
        cache_key = f"{asset_code}_{end_date}"

        if cache_key in self._cache:
            prices, cached_at = self._cache[cache_key]
            if timezone.now() - cached_at < self._ttl:
                return prices
            else:
                del self._cache[cache_key]

        return None

    def set(
        self,
        asset_code: str,
        end_date: date,
        prices: list[float]
    ) -> None:
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
        days_back: int = 252
    ) -> list[float] | None:
        """
        获取资产历史收盘价。

        Args:
            asset_code: 资产代码（如 "510300"、"000300"）
            end_date: 截止日期
            days_back: 向前取多少个交易日

        Returns:
            收盘价列表（从旧到新），或 None
        """
        # 优先查缓存
        cached_prices = self.cache.get(asset_code, end_date)
        if cached_prices and len(cached_prices) >= days_back:
            return cached_prices[-days_back:]

        # 从 data_center 事实表获取
        prices = self._fetch_from_data_center(asset_code, end_date, days_back)

        if prices:
            self.cache.set(asset_code, end_date, prices)

        return prices

    def get_multiple_prices(
        self,
        asset_codes: list[str],
        end_date: date,
        days_back: int = 252
    ) -> dict[str, list[float]]:
        """批量获取多个资产的历史价格。"""
        result = {}

        for asset_code in asset_codes:
            prices = self.get_prices(asset_code, end_date, days_back)
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
    ) -> list[float] | None:
        """从 data_center 事实表读取历史价格"""
        try:
            prices = fetch_close_prices_from_data_center(
                asset_code=asset_code,
                end_date=end_date,
                days_back=days_back,
            )
            if not prices:
                logger.warning("data_center 无法获取 %s 的历史价格", asset_code)
                return None
            return prices

        except Exception:
            logger.exception("从 data_center 获取 %s 历史价格失败", asset_code)
            return None
