"""
Market Data 桥接层

将统一 market_data 能力层桥接到现有业务模块的 Protocol 接口。
业务模块（如 apps/realtime）只依赖桥接层，不依赖具体数据源。
"""

import logging
from typing import List, Optional

from apps.market_data.domain.enums import DataCapability
from apps.market_data.infrastructure.registries.source_registry import SourceRegistry
from apps.realtime.domain.entities import AssetType, RealtimePrice
from apps.realtime.domain.protocols import PriceDataProviderProtocol

logger = logging.getLogger(__name__)


class MarketDataBridgePriceProvider(PriceDataProviderProtocol):
    """Market Data → Realtime 桥接 Provider

    从 SourceRegistry 获取 REALTIME_QUOTE provider，
    将 QuoteSnapshot 转换为 realtime 模块的 RealtimePrice。

    这样 apps/realtime 只依赖桥接层，不依赖东方财富/AKShare。
    """

    def __init__(self, registry: SourceRegistry) -> None:
        self._registry = registry

    def get_realtime_price(self, asset_code: str) -> RealtimePrice | None:
        """获取单个资产的实时价格"""
        prices = self.get_realtime_prices_batch([asset_code])
        return prices[0] if prices else None

    def get_realtime_prices_batch(
        self, asset_codes: list[str]
    ) -> list[RealtimePrice]:
        """批量获取实时价格

        使用 call_with_failover 自动遍历所有可用 provider：
        第一个源失败或返回空，自动尝试下一个。
        """
        snapshots = self._registry.call_with_failover(
            DataCapability.REALTIME_QUOTE,
            lambda p: p.get_quote_snapshots(asset_codes),
        )
        if not snapshots:
            logger.warning("所有 REALTIME_QUOTE provider 均无法获取数据")
            return []

        results: list[RealtimePrice] = []
        for snap in snapshots:
            try:
                results.append(
                    RealtimePrice(
                        asset_code=snap.stock_code,
                        asset_type=self._infer_asset_type(snap.stock_code),
                        price=str(snap.price),
                        change=str(snap.change) if snap.change is not None else None,
                        change_pct=(
                            str(snap.change_pct)
                            if snap.change_pct is not None
                            else None
                        ),
                        volume=snap.volume,
                        timestamp=snap.fetched_at,
                        source=f"market_data:{snap.source}",
                    )
                )
            except Exception:
                logger.warning("转换 QuoteSnapshot → RealtimePrice 失败: %s", snap.stock_code)
                continue

        logger.info(
            "Market Data 桥接: 请求 %d 只, 转换成功 %d 只",
            len(asset_codes),
            len(results),
        )
        return results

    def is_available(self) -> bool:
        """检查是否有可用的 REALTIME_QUOTE provider"""
        return self._registry.get_provider(DataCapability.REALTIME_QUOTE) is not None

    @staticmethod
    def _infer_asset_type(stock_code: str) -> AssetType:
        """根据股票代码推断资产类型"""
        if "." in stock_code:
            suffix = stock_code.split(".")[1]
            if suffix in ("SH", "SZ", "BJ"):
                return AssetType.EQUITY
        return AssetType.UNKNOWN
