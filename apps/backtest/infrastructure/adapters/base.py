"""
Base Protocol and Exceptions for Asset Price Adapters.

Infrastructure layer - defines the interface for fetching asset prices.
"""

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


class AssetPriceUnavailableError(Exception):
    """资产价格不可用异常"""

    pass


class AssetPriceValidationError(Exception):
    """资产价格验证异常"""

    pass


@dataclass(frozen=True)
class AssetPricePoint:
    """资产价格数据点"""

    asset_class: str  # 资产类别 (a_share_growth, a_share_value, china_bond, gold, commodity, cash)
    price: float
    as_of_date: date
    source: str = "unknown"

    def __post_init__(self) -> None:
        """Validate and normalize one immutable price observation."""

        if not isinstance(self.asset_class, str) or not self.asset_class.strip():
            raise AssetPriceValidationError("资产类别不能为空")
        if isinstance(self.price, bool) or not isinstance(self.price, (int, float, Decimal)):
            raise AssetPriceValidationError(f"价格必须是数值类型: {type(self.price)}")
        try:
            normalized_price = float(self.price)
        except (OverflowError, TypeError, ValueError) as exc:
            raise AssetPriceValidationError("价格必须是有限正数") from exc
        if not math.isfinite(normalized_price) or normalized_price <= 0:
            raise AssetPriceValidationError("价格必须是有限正数")
        if type(self.as_of_date) is not date:
            raise AssetPriceValidationError("价格日期必须是 date")
        if not isinstance(self.source, str) or not self.source.strip():
            raise AssetPriceValidationError("价格来源不能为空")
        if len(self.asset_class) > 100 or len(self.source) > 128:
            raise AssetPriceValidationError("价格资产或来源超长")
        if any(ord(character) < 32 for character in self.asset_class + self.source):
            raise AssetPriceValidationError("价格资产或来源包含控制字符")

        object.__setattr__(self, "asset_class", self.asset_class.strip())
        object.__setattr__(self, "price", normalized_price)
        object.__setattr__(self, "source", self.source.strip())


def get_runtime_asset_proxy_map() -> dict[str, str]:
    """Read asset proxy settings through the owning config center service."""

    from apps.config_center.application.config_summary_service import (
        get_config_center_summary_service,
    )

    return get_config_center_summary_service().get_runtime_asset_proxy_map()


def get_asset_class_tickers() -> dict[str, str]:
    """从系统配置读取资产类别代理代码。"""
    return get_runtime_asset_proxy_map()


class AssetPriceAdapterProtocol(Protocol):
    """
    资产价格适配器协议

    所有价格数据源适配器必须实现此协议。
    """

    source_name: str

    def get_price(self, asset_class: str, as_of_date: date) -> float | None:
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
        self, asset_class: str, start_date: date, end_date: date
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


class BaseAssetPriceAdapter:
    """
    资产价格适配器基类

    提供通用的辅助方法。
    """

    source_name: str = "base"

    def supports(self, asset_class: str) -> bool:
        """默认实现：子类应覆盖"""
        return asset_class in get_asset_class_tickers()

    def get_price(self, asset_class: str, as_of_date: date) -> float | None:
        """默认实现：子类应覆盖"""
        raise NotImplementedError

    def get_prices(
        self, asset_class: str, start_date: date, end_date: date
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
        tickers = get_asset_class_tickers()
        if asset_class not in tickers:
            raise AssetPriceValidationError(
                f"不支持的资产类别: {asset_class}，" f"支持的类别: {list(tickers.keys())}"
            )
