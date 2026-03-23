"""
Realtime Module - Domain Layer Entities

This module contains the core business entities for the realtime price monitoring system.
Following AgomSaaS architecture rules:
- Only Python standard library allowed
- Using @dataclass(frozen=True) for value objects
- No external dependencies (no Django, no pandas)
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional


class AssetType(Enum):
    """资产类型枚举"""
    EQUITY = "equity"           # 股票
    FUND = "fund"               # 基金
    INDEX = "index"             # 指数
    BOND = "bond"               # 债券
    FUTURES = "futures"         # 期货
    UNKNOWN = "unknown"         # 未知类型


class PriceUpdateStatus(Enum):
    """价格更新状态枚举"""
    SUCCESS = "success"         # 更新成功
    FAILED = "failed"           # 更新失败
    NO_CHANGE = "no_change"     # 价格无变化
    SKIPPED = "skipped"         # 已跳过（如非交易时间）


@dataclass(frozen=True)
class RealtimePrice:
    """实时价格值对象

    Attributes:
        asset_code: 资产代码（如 ASSET_CODE）
        asset_type: 资产类型
        price: 当前价格
        change: 价格变动（绝对值）
        change_pct: 价格变动百分比
        volume: 成交量
        timestamp: 价格时间戳
        source: 数据来源（tushare/akshare等）
    """
    asset_code: str
    asset_type: AssetType
    price: Decimal
    change: Decimal | None
    change_pct: Decimal | None
    volume: int | None
    timestamp: datetime
    source: str

    def to_dict(self) -> dict:
        """转换为字典格式（用于API响应）"""
        return {
            "asset_code": self.asset_code,
            "asset_type": self.asset_type.value,
            "price": float(self.price),
            "change": float(self.change) if self.change is not None else None,
            "change_pct": float(self.change_pct) if self.change_pct is not None else None,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source
        }


@dataclass(frozen=True)
class PriceUpdate:
    """价格更新事件值对象

    Attributes:
        asset_code: 资产代码
        old_price: 旧价格
        new_price: 新价格
        status: 更新状态
        timestamp: 更新时间戳
        error_message: 错误信息（如果更新失败）
    """
    asset_code: str
    old_price: Decimal | None
    new_price: Decimal | None
    status: PriceUpdateStatus
    timestamp: datetime
    error_message: str | None = None

    @property
    def price_changed(self) -> bool:
        """价格是否发生变化"""
        if self.old_price is None or self.new_price is None:
            return False
        return self.old_price != self.new_price

    @property
    def price_change(self) -> Decimal | None:
        """价格变动（绝对值）"""
        if self.old_price is None or self.new_price is None:
            return None
        return self.new_price - self.old_price

    @property
    def price_change_pct(self) -> Decimal | None:
        """价格变动百分比"""
        if self.old_price is None or self.new_price is None or self.old_price == 0:
            return None
        return (self.new_price - self.old_price) / self.old_price * Decimal(100)

    def to_dict(self) -> dict:
        """转换为字典格式（用于API响应）"""
        return {
            "asset_code": self.asset_code,
            "old_price": float(self.old_price) if self.old_price is not None else None,
            "new_price": float(self.new_price) if self.new_price is not None else None,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "error_message": self.error_message
        }


@dataclass(frozen=True)
class PricePollingConfig:
    """价格轮询配置值对象

    Attributes:
        polling_interval: 轮询间隔（秒）
        batch_size: 批量查询大小（每次查询的资产数量）
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        timeout: 请求超时（秒）
    """
    polling_interval: int = 30      # 默认30秒
    batch_size: int = 100           # 每次批量查询100个资产
    max_retries: int = 3            # 最多重试3次
    retry_delay: int = 5            # 重试延迟5秒
    timeout: int = 30               # 请求超时30秒

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "polling_interval": self.polling_interval,
            "batch_size": self.batch_size,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "timeout": self.timeout
        }


@dataclass(frozen=True)
class PriceSnapshot:
    """价格快照值对象

    用于批量返回多个资产的价格信息

    Attributes:
        timestamp: 快照时间戳
        prices: 价格列表
        total_assets: 总资产数
        success_count: 成功获取价格的资产数
        failed_count: 失败的资产数
    """
    timestamp: datetime
    prices: list[RealtimePrice]
    total_assets: int
    success_count: int
    failed_count: int

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_assets == 0:
            return 0.0
        return self.success_count / self.total_assets

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "prices": [price.to_dict() for price in self.prices],
            "total_assets": self.total_assets,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "success_rate": self.success_rate
        }
