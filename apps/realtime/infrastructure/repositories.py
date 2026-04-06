"""
Realtime Module - Infrastructure Layer Repositories

This module provides concrete implementations of the repository protocols.
Following AgomSaaS architecture rules:
- Infrastructure layer can use Django ORM and external libraries
- Implements the Protocol interfaces defined in Domain layer
"""

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional

from django.core.cache import cache
from django.db import models
from django.utils import timezone

from apps.data_center.infrastructure.repositories import PriceBarRepository, QuoteSnapshotRepository
from apps.realtime.domain.entities import (
    AssetType,
    PriceSnapshot,
    PriceUpdate,
    PriceUpdateStatus,
    RealtimePrice,
)
from apps.realtime.domain.protocols import (
    PriceDataProviderProtocol,
    RealtimePriceRepositoryProtocol,
    WatchlistProviderProtocol,
)
from apps.simulated_trading.infrastructure.models import PositionModel

logger = logging.getLogger(__name__)


class RedisRealtimePriceRepository(RealtimePriceRepositoryProtocol):
    """基于 Redis 的实时价格仓储

    使用 Django cache 后端（配置为 Redis）存储实时价格
    缓存键格式: realtime:price:{asset_code}
    缓存过期时间: 5 分钟
    """

    CACHE_KEY_PREFIX = "realtime:price"
    CACHE_TIMEOUT = 300  # 5分钟过期

    def save_price(self, price: RealtimePrice) -> None:
        """保存单个实时价格到 Redis"""
        cache_key = f"{self.CACHE_KEY_PREFIX}:{price.asset_code}"
        cache.set(cache_key, price.to_dict(), timeout=self.CACHE_TIMEOUT)
        logger.debug(f"Saved price for {price.asset_code}: {price.price}")

    def save_prices_batch(self, prices: list[RealtimePrice]) -> None:
        """批量保存实时价格到 Redis"""
        cache_data = {
            f"{self.CACHE_KEY_PREFIX}:{p.asset_code}": p.to_dict()
            for p in prices
        }
        # 使用 cache.set_many 批量设置
        cache.set_many(cache_data, timeout=self.CACHE_TIMEOUT)
        logger.info(f"Batch saved {len(prices)} prices to Redis")

    def get_latest_price(self, asset_code: str) -> RealtimePrice | None:
        """从 Redis 获取资产的最新价格"""
        cache_key = f"{self.CACHE_KEY_PREFIX}:{asset_code}"
        data = cache.get(cache_key)

        if data is None:
            return None

        try:
            return self._dict_to_price(data)
        except Exception as e:
            logger.error(f"Failed to deserialize price for {asset_code}: {e}")
            return None

    def get_latest_prices(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的最新价格"""
        cache_keys = [f"{self.CACHE_KEY_PREFIX}:{code}" for code in asset_codes]
        cache_data_dict = cache.get_many(cache_keys)

        result = []
        for code in asset_codes:
            cache_key = f"{self.CACHE_KEY_PREFIX}:{code}"
            data = cache_data_dict.get(cache_key)
            if data:
                try:
                    result.append(self._dict_to_price(data))
                except Exception as e:
                    logger.error(f"Failed to deserialize price for {code}: {e}")

        return result

    def _dict_to_price(self, data: dict) -> RealtimePrice:
        """将字典转换为 RealtimePrice 对象"""
        return RealtimePrice(
            asset_code=data["asset_code"],
            asset_type=AssetType(data["asset_type"]),
            price=str(data["price"]),
            change=str(data["change"]) if data.get("change") else None,
            change_pct=str(data["change_pct"]) if data.get("change_pct") else None,
            volume=data.get("volume"),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data["source"]
        )


class TusharePriceDataProvider(PriceDataProviderProtocol):
    """Tushare 价格数据提供者

    从 Tushare Pro API 获取实时行情数据
    使用现有的 TushareAdapter 适配器
    """

    def __init__(self):
        self._quote_repo = QuoteSnapshotRepository()
        self._price_repo = PriceBarRepository()
        self._is_available = True

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """获取单个资产的实时价格

        注意：Tushare免费版只能获取历史数据，"实时"实际上是最新交易日数据
        """
        try:
            quote = self._quote_repo.get_latest(asset_code)
            if quote is not None:
                return RealtimePrice(
                    asset_code=asset_code,
                    asset_type=self._get_asset_type(asset_code),
                    price=str(quote.current_price),
                    change=None,
                    change_pct=None,
                    volume=int(quote.volume) if quote.volume is not None else None,
                    timestamp=quote.snapshot_at,
                    source=quote.source or "data_center",
                )

            latest_bar = self._price_repo.get_latest(asset_code)
            if latest_bar is None:
                logger.warning(f"No price data found for {asset_code}")
                return None

            return RealtimePrice(
                asset_code=asset_code,
                asset_type=self._get_asset_type(asset_code),
                price=str(latest_bar.close),
                change=None,
                change_pct=None,
                volume=int(latest_bar.volume) if latest_bar.volume is not None else None,
                timestamp=timezone.now(),
                source=latest_bar.source or "data_center"
            )

        except Exception as e:
            logger.error(f"Failed to get realtime price for {asset_code}: {e}")
            return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的实时价格"""
        prices = []

        for code in asset_codes:
            price = self.get_realtime_price(code)
            if price:
                prices.append(price)

        logger.info(f"Retrieved {len(prices)}/{len(asset_codes)} prices from Tushare")
        return prices

    def is_available(self) -> bool:
        """检查 Tushare 数据源是否可用"""
        if not self._is_available:
            return False

        try:
            # 尝试获取一个测试数据
            test_price = self.get_realtime_price("000001.SZ")
            return test_price is not None
        except Exception as e:
            logger.error(f"Tushare data source unavailable: {e}")
            self._is_available = False
            return False

    def _convert_to_tushare_code(self, asset_code: str) -> str:
        """转换资产代码为 Tushare 格式

        例如: 600000.SH -> 600000.SH (已符合格式)
        """
        # 假设输入已经是 Tushare 格式
        return asset_code

    def _get_asset_type(self, asset_code: str) -> AssetType:
        """根据资产代码判断资产类型"""
        if "." in asset_code:
            suffix = asset_code.split(".")[1]
            if suffix in ["SH", "SZ", "BJ"]:
                return AssetType.EQUITY
        elif asset_code.startswith("000"):
            return AssetType.INDEX
        return AssetType.UNKNOWN


class AKSharePriceDataProvider(PriceDataProviderProtocol):
    """AKShare 价格数据提供者

    从 AKShare 获取实时行情数据
    完全免费，无需 Token
    """

    def __init__(self):
        self._quote_repo = QuoteSnapshotRepository()
        self._price_repo = PriceBarRepository()
        self._is_available = True

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """获取单个资产的实时价格

        AKShare 提供实时行情数据，无需 Token
        """
        try:
            quote = self._quote_repo.get_latest(asset_code)
            if quote is not None:
                return RealtimePrice(
                    asset_code=asset_code,
                    asset_type=self._get_asset_type(asset_code),
                    price=str(quote.current_price),
                    change=None,
                    change_pct=None,
                    volume=int(quote.volume) if quote.volume is not None else None,
                    timestamp=quote.snapshot_at,
                    source=quote.source or "data_center",
                )

            latest_bar = self._price_repo.get_latest(asset_code)
            if latest_bar is None:
                logger.warning(f"No price data found for {asset_code}")
                return None

            return RealtimePrice(
                asset_code=asset_code,
                asset_type=self._get_asset_type(asset_code),
                price=str(latest_bar.close),
                change=None,
                change_pct=None,
                volume=int(latest_bar.volume) if latest_bar.volume is not None else None,
                timestamp=timezone.now(),
                source=latest_bar.source or "data_center"
            )

        except Exception as e:
            logger.error(f"Failed to get realtime price for {asset_code} from AKShare: {e}")
            return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取多个资产的实时价格

        AKShare 可以一次性获取所有股票的实时行情
        """
        prices = []
        for code in asset_codes:
            price = self.get_realtime_price(code)
            if price is not None:
                prices.append(price)
        logger.info(f"Retrieved {len(prices)}/{len(asset_codes)} prices from data_center")
        return prices

    def is_available(self) -> bool:
        """检查 AKShare 数据源是否可用"""
        if not self._is_available:
            return False

        try:
            return (
                self._quote_repo.get_latest("000001.SZ") is not None
                or self._price_repo.get_latest("000001.SZ") is not None
            )
        except Exception as e:
            logger.error(f"AKShare data source unavailable: {e}")
            self._is_available = False
            return False

    def _convert_to_akshare_code(self, asset_code: str) -> str:
        """转换资产代码为 AKShare 格式

        Tushare格式: 000001.SZ → AKShare格式: 000001
        Tushare格式: 600000.SH → AKShare格式: 600000
        """
        if "." in asset_code:
            code, _ = asset_code.split(".")
            return code
        return asset_code

    def _get_asset_type(self, asset_code: str) -> AssetType:
        """根据资产代码判断资产类型"""
        if "." in asset_code:
            suffix = asset_code.split(".")[1]
            if suffix in ["SH", "SZ", "BJ"]:
                return AssetType.EQUITY
        elif asset_code.startswith("000"):
            return AssetType.INDEX
        return AssetType.UNKNOWN


class DatabaseWatchlistProvider(WatchlistProviderProtocol):
    """基于数据库的关注池提供者

    从数据库中获取持仓资产和关注池资产
    """

    def get_held_assets(self) -> list[str]:
        """获取所有持仓资产代码"""
        # 查询所有非零持仓
        positions = PositionModel._default_manager.filter(
            quantity__gt=0
        ).values_list("asset_code", flat=True).distinct()

        return list(positions)

    def get_watchlist_assets(self, user_id: str | None = None) -> list[str]:
        """获取关注池资产代码

        从 asset_analysis 模块的 AssetPoolEntry 中查询
        pool_type='watch' 且 is_active=True 的资产。
        """
        try:
            from apps.asset_analysis.infrastructure.models import AssetPoolEntry

            codes = AssetPoolEntry._default_manager.filter(
                pool_type="watch",
                is_active=True,
            ).values_list("asset_code", flat=True).distinct()

            result = list(codes)
            if result:
                logger.info("Loaded %d watchlist assets from asset pool", len(result))
            return result

        except Exception as e:
            logger.warning("Failed to load watchlist assets: %s", e)
            return []

    def get_all_monitored_assets(self) -> list[str]:
        """获取所有需要监控的资产（持仓 + 关注池）"""
        held = set(self.get_held_assets())
        watchlist = set(self.get_watchlist_assets())

        # 去重并返回
        return list(held | watchlist)


class DataCenterPriceDataProvider(PriceDataProviderProtocol):
    """Price provider backed by data_center quote/price facts."""

    def __init__(self):
        from apps.data_center.infrastructure.repositories import (
            PriceBarRepository,
            QuoteSnapshotRepository,
        )

        self._quote_repo = QuoteSnapshotRepository()
        self._bar_repo = PriceBarRepository()

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        try:
            quote = self._quote_repo.get_latest(asset_code)
            if quote is not None:
                return RealtimePrice(
                    asset_code=asset_code,
                    asset_type=self._get_asset_type(asset_code),
                    price=Decimal(str(quote.current_price)),
                    change=None,
                    change_pct=None,
                    volume=int(quote.volume) if quote.volume is not None else None,
                    timestamp=quote.snapshot_at,
                    source=quote.source,
                )

            bar = self._bar_repo.get_latest(asset_code)
            if bar is None:
                return None
            return RealtimePrice(
                asset_code=asset_code,
                asset_type=self._get_asset_type(asset_code),
                price=Decimal(str(bar.close)),
                change=None,
                change_pct=None,
                volume=int(bar.volume) if bar.volume is not None else None,
                timestamp=timezone.now(),
                source=bar.source,
            )
        except Exception:
            logger.warning(
                "Failed to read realtime price from data_center: %s",
                asset_code,
                exc_info=True,
            )
            return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        prices: list[RealtimePrice] = []
        for code in asset_codes:
            price = self.get_realtime_price(code)
            if price is not None:
                prices.append(price)
        return prices

    def is_available(self) -> bool:
        return True

    def _get_asset_type(self, asset_code: str) -> AssetType:
        if asset_code.endswith(".OF") or asset_code.endswith(".OFC"):
            return AssetType.FUND
        if asset_code.startswith(("000", "399")) and "." not in asset_code:
            return AssetType.INDEX
        if "." in asset_code:
            suffix = asset_code.split(".")[1]
            if suffix in ["SH", "SZ", "BJ"]:
                return AssetType.EQUITY
        return AssetType.UNKNOWN


class CompositePriceDataProvider(PriceDataProviderProtocol):
    """组合价格数据提供者

    支持多个数据源，自动故障转移
    """

    def __init__(self, providers: list[PriceDataProviderProtocol]):
        self.providers = providers

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """依次尝试从各个数据源获取价格"""
        last_error = None

        for provider in self.providers:
            try:
                price = provider.get_realtime_price(asset_code)
                if price:
                    return price
            except Exception as e:
                last_error = e
                logger.warning(f"Provider {provider.__class__.__name__} failed: {e}")

        logger.error(f"All providers failed for {asset_code}, last error: {last_error}")
        return None

    def get_realtime_prices_batch(self, asset_codes: list[str]) -> list[RealtimePrice]:
        """批量获取价格（使用第一个可用的提供者）"""
        for provider in self.providers:
            try:
                prices = provider.get_realtime_prices_batch(asset_codes)
                if prices:
                    return prices
            except Exception as e:
                logger.warning(f"Provider {provider.__class__.__name__} batch failed: {e}")

        return []

    def is_available(self) -> bool:
        """检查是否有可用的数据源"""
        return any(provider.is_available() for provider in self.providers)

