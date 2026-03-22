"""
Rotation Module Infrastructure Layer - Price Data Adapter

通过 market_data 数据中台获取历史价格数据。
不再直连 Tushare/AkShare，统一走 SourceRegistry failover + 熔断机制。
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class PriceDataCache:
    """Simple cache for price data to reduce API calls"""

    def __init__(self, ttl_seconds: int = 3600):
        self._cache: Dict[str, tuple[List[float], datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(
        self,
        asset_code: str,
        end_date: date
    ) -> Optional[List[float]]:
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
        prices: List[float]
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

    通过 market_data 数据中台的 SourceRegistry 获取历史价格，
    自动享受 failover、熔断、多源切换能力。
    """

    def __init__(
        self,
        cache: Optional[PriceDataCache] = None,
    ):
        self.cache = cache or PriceDataCache()

    def get_prices(
        self,
        asset_code: str,
        end_date: date,
        days_back: int = 252
    ) -> Optional[List[float]]:
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

        # 通过 market_data 数据中台获取
        prices = self._fetch_from_market_data(asset_code, end_date, days_back)

        if prices:
            self.cache.set(asset_code, end_date, prices)

        return prices

    def get_multiple_prices(
        self,
        asset_codes: List[str],
        end_date: date,
        days_back: int = 252
    ) -> Dict[str, List[float]]:
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
    def _fetch_from_market_data(
        asset_code: str,
        end_date: date,
        days_back: int,
    ) -> Optional[List[float]]:
        """通过 market_data SourceRegistry 获取历史价格"""
        try:
            from apps.market_data.application.registry_factory import get_registry
            from apps.market_data.domain.enums import DataCapability

            registry = get_registry()

            # 加缓冲天数，应对非交易日
            start_date = end_date - timedelta(days=days_back + 30)
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")

            bars = registry.call_with_failover(
                DataCapability.HISTORICAL_PRICE,
                lambda provider: provider.get_historical_prices(
                    asset_code, start_str, end_str
                ),
            )

            if not bars:
                logger.warning(
                    "market_data 数据中台无法获取 %s 的历史价格", asset_code
                )
                return None

            # 提取收盘价，按日期升序
            prices = [bar.close for bar in bars]
            return prices[-days_back:] if len(prices) > days_back else prices

        except Exception:
            logger.exception(
                "通过 market_data 获取 %s 历史价格失败", asset_code
            )
            return None
