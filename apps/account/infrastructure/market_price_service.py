"""
Market Price Service - Account Module

统一行情价格服务，为持仓创建提供可追溯的价格来源。
复用 simulated_trading 模块的 MarketDataProvider，遵循 DRY 原则。

Architecture:
- Infrastructure 层：外部数据源适配
- 提供 get_current_price(asset_code) 接口
- 价格来源可追溯（包含 source 和 timestamp）
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from django.utils import timezone

from apps.simulated_trading.infrastructure.market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class MarketPriceService:
    """
    市场价格服务

    为 Account 模块提供统一的行情价格获取接口。
    复用 simulated_trading 模块的 MarketDataProvider，避免重复实现。

    功能：
    - 获取资产最新价格
    - 价格来源可追溯
    - 支持缓存优化
    - 错误处理和降级
    """

    def __init__(self, cache_ttl_minutes: int = 30):
        """
        初始化市场价格服务

        Args:
            cache_ttl_minutes: 缓存有效期（分钟）
        """
        self._provider = None
        self.cache_ttl_minutes = cache_ttl_minutes

    @property
    def provider(self) -> MarketDataProvider:
        """延迟初始化 MarketDataProvider（避免启动时必须配置 token）"""
        if self._provider is None:
            self._provider = MarketDataProvider(cache_ttl_minutes=self.cache_ttl_minutes)
        return self._provider

    def get_current_price(self, asset_code: str, trade_date: date = None) -> Decimal | None:
        """
        获取资产当前价格

        Args:
            asset_code: 资产代码（如 'ASSET_CODE'）
            trade_date: 交易日期（None 表示最新）

        Returns:
            Decimal: 价格（元），获取失败返回 None

        Raises:
            ValueError: 当资产代码无效时
        """
        if not asset_code:
            raise ValueError("资产代码不能为空")

        # 规范化资产代码
        asset_code = self._normalize_asset_code(asset_code)

        # 获取价格
        price = self.provider.get_price(asset_code, trade_date)

        if price is None:
            logger.warning(f"未获取到资产价格: {asset_code} @ {trade_date or '最新'}")
            return None

        # 转换为 Decimal
        try:
            return Decimal(str(price))
        except (ValueError, TypeError, Exception) as e:
            logger.error(f"价格格式转换失败: {price} -> Decimal, 错误: {e}")
            return None

    def get_prices_batch(
        self,
        asset_codes: list[str],
        trade_date: date = None
    ) -> dict[str, Decimal | None]:
        """
        批量获取资产价格

        Args:
            asset_codes: 资产代码列表
            trade_date: 交易日期（None 表示最新）

        Returns:
            Dict[str, Optional[Decimal]]: {asset_code: price}
        """
        results = {}
        for code in asset_codes:
            results[code] = self.get_current_price(code, trade_date)
        return results

    def get_price_with_metadata(
        self,
        asset_code: str,
        trade_date: date = None
    ) -> dict[str, Any] | None:
        """
        获取资产价格及元数据

        Args:
            asset_code: 资产代码
            trade_date: 交易日期（None 表示最新）

        Returns:
            Dict with keys:
                - price: Decimal (价格)
                - asset_code: str (资产代码)
                - source: str (数据源)
                - timestamp: datetime (获取时间)
                - trade_date: date (交易日期)
            获取失败返回 None
        """
        price = self.get_current_price(asset_code, trade_date)
        if price is None:
            return None

        return {
            "price": price,
            "asset_code": asset_code,
            "source": "MarketDataProvider",  # 数据源
            "timestamp": timezone.now(),
            "trade_date": trade_date or date.today(),
        }

    def clear_cache(self) -> None:
        """清空价格缓存"""
        if self._provider is not None:
            self._provider.clear_cache()
            logger.info("市场价格服务缓存已清空")

    def _normalize_asset_code(self, asset_code: str) -> str:
        """
        规范化资产代码

        Args:
            asset_code: 原始资产代码

        Returns:
            规范化后的资产代码
        """
        # 去除空格
        asset_code = asset_code.strip()

        # 统一为大写
        asset_code = asset_code.upper()

        # 确保后缀格式正确（如 .SZ, .SH, .BJ）
        # 如果是 6 位数字代码且没有后缀，根据规则添加
        if len(asset_code) == 6 and asset_code.isdigit():
            if asset_code.startswith('0') or asset_code.startswith('3'):
                # 深圳主板或创业板
                asset_code = f"{asset_code}.SZ"
            elif asset_code.startswith('6'):
                # 上海主板
                asset_code = f"{asset_code}.SH"
            elif asset_code.startswith('8') or asset_code.startswith('4'):
                # 新三板或北京交易所
                asset_code = f"{asset_code}.BJ"

        return asset_code

    def is_available(self) -> bool:
        """
        检查数据源是否可用

        Returns:
            bool: 数据源是否可用
        """
        try:
            # 尝试获取一个常见资产的价格来测试
            test_price = self.get_current_price("000001.SZ")
            return test_price is not None
        except Exception as e:
            logger.warning(f"市场价格服务不可用: {e}")
            return False


# 全局单例（延迟初始化）
_price_service_instance: MarketPriceService | None = None


def get_market_price_service() -> MarketPriceService:
    """
    获取市场价格服务单例

    Returns:
        MarketPriceService: 全局唯一的服务实例
    """
    global _price_service_instance
    if _price_service_instance is None:
        _price_service_instance = MarketPriceService()
    return _price_service_instance
