"""
Base Protocol and Exceptions for Asset Price Adapters.

Infrastructure layer - defines the interface for fetching asset prices.
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional, Protocol
from dataclasses import dataclass


class AssetPriceUnavailableError(Exception):
    """资产价格不可用异常"""
    pass


class AssetPriceValidationError(Exception):
    """资产价格验证异常"""
    pass


@dataclass
class AssetPricePoint:
    """资产价格数据点"""
    asset_class: str  # 资产类别 (a_share_growth, a_share_value, china_bond, gold, commodity, cash)
    price: float
    as_of_date: date
    source: str = "unknown"

    def __post_init__(self):
        """验证数据"""
        if not self.asset_class:
            raise AssetPriceValidationError("资产类别不能为空")
        if not isinstance(self.price, (int, float)):
            raise AssetPriceValidationError(f"价格必须是数值类型: {type(self.price)}")
        if self.price < 0:
            raise AssetPriceValidationError(f"价格不能为负数: {self.price}")


# 资产类别与对应标的代码映射
ASSET_CLASS_TICKERS = {
    "a_share_growth": "000300.SH",      # 沪深300 (成长风格 proxy)
    "a_share_value": "000905.SH",       # 中证500 (价值风格 proxy)
    "china_bond": "TS01.CS",            # 中债财富总指数
    "gold": "AU9999.SGE",               # 上海黄金现货
    "commodity": "NHCI.NH",             # 南华商品指数
    "cash": "CASH",                     # 现金 (固定价格 1.0)
}


class AssetPriceAdapterProtocol(Protocol):
    """
    资产价格适配器协议

    所有价格数据源适配器必须实现此协议。
    """

    source_name: str

    def get_price(
        self,
        asset_class: str,
        as_of_date: date
    ) -> Optional[float]:
        """
        获取指定资产在指定日期的价格

        Args:
            asset_class: 资产类别
            as_of_date: 查询日期

        Returns:
            Optional[float]: 价格，如果不可用则返回 None

        Raises:
            AssetPriceUnavailableError: 数据源不可用
            AssetPriceValidationError: 数据验证失败
        """
        ...

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

        Raises:
            AssetPriceUnavailableError: 数据源不可用
            AssetPriceValidationError: 数据验证失败
        """
        ...

    def supports(self, asset_class: str) -> bool:
        """
        检查是否支持指定资产类别

        Args:
            asset_class: 资产类别

        Returns:
            bool: 是否支持
        """
        ...


class BaseAssetPriceAdapter(ABC):
    """
    资产价格适配器基类

    提供通用的辅助方法。
    """

    source_name: str = "base"

    def supports(self, asset_class: str) -> bool:
        """默认实现：子类应覆盖"""
        return asset_class in ASSET_CLASS_TICKERS

    def get_price(
        self,
        asset_class: str,
        as_of_date: date
    ) -> Optional[float]:
        """默认实现：子类应覆盖"""
        raise NotImplementedError

    def get_prices(
        self,
        asset_class: str,
        start_date: date,
        end_date: date
    ) -> list[AssetPricePoint]:
        """默认实现：子类应覆盖"""
        raise NotImplementedError

    def _get_cash_price(self) -> float:
        """获取现金价格（固定为 1.0）"""
        return 1.0

    def _validate_asset_class(self, asset_class: str) -> None:
        """
        验证资产类别

        Args:
            asset_class: 资产类别

        Raises:
            AssetPriceValidationError: 不支持的资产类别
        """
        if asset_class not in ASSET_CLASS_TICKERS:
            raise AssetPriceValidationError(
                f"不支持的资产类别: {asset_class}，"
                f"支持的类别: {list(ASSET_CLASS_TICKERS.keys())}"
            )
