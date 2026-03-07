"""
Composite Asset Price Adapter.

组合多个数据源，支持 failover 和默认价格配置。
"""

import logging
from datetime import date, timedelta
from typing import Optional

from .base import (
    AssetPriceAdapterProtocol,
    AssetPricePoint,
    AssetPriceUnavailableError,
    get_asset_class_tickers,
)

logger = logging.getLogger(__name__)


DEFAULT_PRICES: dict[str, float] = {}


class CompositeAssetPriceAdapter:
    """
    组合资产价格适配器

    支持多个数据源的 failover 机制，当主数据源失败时自动切换到备用数据源。
    如果所有数据源都失败，仅在显式注入 default_prices 时才返回默认价格。
    """

    source_name = "composite"

    def __init__(
        self,
        adapters: list[AssetPriceAdapterProtocol],
        use_defaults: bool = False,
        default_prices: dict[str, float] | None = None
    ):
        """
        初始化组合适配器

        Args:
            adapters: 数据源适配器列表（按优先级排序）
        use_defaults: 当所有数据源都失败时，是否使用注入的默认价格
            default_prices: 默认价格配置
        """
        self._adapters = adapters
        self._use_defaults = use_defaults
        self._default_prices = default_prices or DEFAULT_PRICES.copy()

        # 内部缓存
        self._price_cache: dict[tuple[str, date], float] = {}

    def supports(self, asset_class: str) -> bool:
        """检查是否支持指定资产类别（至少一个适配器支持或存在默认价格）"""
        if asset_class in self._default_prices:
            return True
        return any(adapter.supports(asset_class) for adapter in self._adapters)

    def get_price(
        self,
        asset_class: str,
        as_of_date: date,
        use_cache: bool = True
    ) -> Optional[float]:
        """
        获取指定资产在指定日期的价格

        按优先级尝试各个数据源，直到有一个成功返回。

        Args:
            asset_class: 资产类别
            as_of_date: 查询日期
            use_cache: 是否使用缓存

        Returns:
            Optional[float]: 价格，如果不可用则返回默认价格或 None
        """
        # 检查缓存
        cache_key = (asset_class, as_of_date)
        if use_cache and cache_key in self._price_cache:
            return self._price_cache[cache_key]

        # 现金固定为 1.0
        if asset_class == "cash":
            return 1.0

        # 尝试各个数据源
        last_error = None
        for adapter in self._adapters:
            if not adapter.supports(asset_class):
                continue

            try:
                price = adapter.get_price(asset_class, as_of_date)
                if price is not None and price > 0:
                    # 缓存成功结果
                    self._price_cache[cache_key] = price
                    return price
            except Exception as e:
                last_error = e
                logger.warning(
                    f"适配器 {adapter.source_name} 获取 {asset_class} 价格失败: {e}"
                )
                continue

        # 所有数据源都失败，返回默认价格
        if self._use_defaults and asset_class in self._default_prices:
            default_price = self._default_prices[asset_class]
            logger.warning(
                f"所有数据源都失败，使用默认价格: {asset_class} = {default_price}"
            )
            self._price_cache[cache_key] = default_price
            return default_price

        # 如果不使用默认价格且没有找到有效价格
        if last_error:
            raise AssetPriceUnavailableError(
                f"无法获取 {asset_class} 在 {as_of_date} 的价格"
            ) from last_error

        return None

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date
    ) -> list[AssetPricePoint]:
        """
        获取指定资产在日期范围内的价格序列

        Args:
            asset_class: 资产类别
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[AssetPricePoint]: 价格数据点列表
        """
        # 尝试各个数据源
        for adapter in self._adapters:
            if not adapter.supports(asset_class):
                continue

            try:
                points = adapter.get_prices(asset_class, start_date, end_date)
                if points:
                    return points
            except Exception as e:
                logger.warning(
                    f"适配器 {adapter.source_name} 获取 {asset_class} 价格序列失败: {e}"
                )
                continue

        # 所有数据源都失败，使用默认价格生成每日序列
        if self._use_defaults and asset_class in self._default_prices:
            default_price = self._default_prices[asset_class]
            logger.warning(
                f"所有数据源都失败，使用默认价格生成序列: {asset_class} = {default_price}"
            )
            points = []
            current = start_date
            while current <= end_date:
                points.append(AssetPricePoint(
                    asset_class=asset_class,
                    price=default_price,
                    as_of_date=current,
                    source="default"
                ))
                current += timedelta(days=1)
            return points

        return []

    def clear_cache(self) -> None:
        """清空价格缓存"""
        self._price_cache.clear()

    def get_supported_assets(self) -> list[str]:
        """获取支持的资产类别列表"""
        assets = set(self._default_prices.keys())
        for adapter in self._adapters:
            assets.update(get_asset_class_tickers().keys())
        return list(assets)


def create_default_price_adapter(tushare_token: str | None = None) -> CompositeAssetPriceAdapter:
    """
    创建默认的资产价格适配器

    Args:
        tushare_token: Tushare API token（可选）

    Returns:
        CompositeAssetPriceAdapter: 组合适配器
    """
    from .tushare_price_adapter import TushareAssetPriceAdapter

    adapters = []

    # 添加 Tushare 适配器（如果提供了 token）
    if tushare_token:
        try:
            adapters.append(TushareAssetPriceAdapter(token=tushare_token))
        except Exception as e:
            logger.warning(f"无法初始化 Tushare 适配器: {e}")

    return CompositeAssetPriceAdapter(
        adapters=adapters,
        use_defaults=False,
        default_prices=DEFAULT_PRICES.copy()
    )
