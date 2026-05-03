"""
Base Protocol and Exceptions for Macro Data Adapters.

Infrastructure layer - defines the interface that all adapters must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Protocol

from core.integration.runtime_settings import get_runtime_macro_publication_lags


class DataSourceUnavailableError(Exception):
    """数据源不可用异常"""
    pass


class DataValidationError(Exception):
    """数据验证异常"""
    pass


@dataclass
class PublicationLag:
    """发布延迟配置"""
    days: int
    description: str


def get_publication_lags() -> dict[str, PublicationLag]:
    """获取发布延迟配置，运行时真源为 runtime metadata。"""
    lags: dict[str, PublicationLag] = {}
    try:
        dynamic_lags = get_runtime_macro_publication_lags()
        for code, item in dynamic_lags.items():
            lags[code] = PublicationLag(
                days=int(item.get("days", 0) or 0),
                description=item.get("description", "实时"),
            )
    except Exception:
        return {}

    return lags


@dataclass
class MacroDataPoint:
    """宏观数据点"""
    code: str
    value: float
    observed_at: date
    published_at: date | None = None
    source: str = "unknown"
    unit: str = ""
    original_unit: str = ""  # 原始单位（数据源返回的单位）

    def __post_init__(self):
        """自动填充发布时间和计算延迟"""
        if self.published_at is None:
            # 如果未指定发布时间，根据配置延迟计算
            lag = get_publication_lags().get(self.code)
            if lag:
                from datetime import timedelta
                self.published_at = self.observed_at + timedelta(days=lag.days)


class MacroAdapterProtocol(Protocol):
    """
    宏观数据适配器协议

    所有数据源适配器必须实现此协议。
    """

    source_name: str

    def supports(self, indicator_code: str) -> bool:
        """
        检查是否支持指定指标

        Args:
            indicator_code: 指标代码

        Returns:
            bool: 是否支持
        """
        ...

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """
        获取指定指标的数据

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表

        Raises:
            DataSourceUnavailableError: 数据源不可用
            DataValidationError: 数据验证失败
        """
        ...


class BaseMacroAdapter(ABC):
    """
    宏观数据适配器基类

    提供通用的辅助方法。
    """

    source_name: str = "base"

    def supports(self, indicator_code: str) -> bool:
        """默认实现：子类应覆盖"""
        return False

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """默认实现：子类必须覆盖"""
        raise NotImplementedError

    def _validate_data_point(self, point: MacroDataPoint) -> None:
        """
        验证数据点

        Args:
            point: 数据点

        Raises:
            DataValidationError: 验证失败
        """
        if not point.code:
            raise DataValidationError("指标代码不能为空")

        if not isinstance(point.value, (int, float)):
            raise DataValidationError(f"指标值必须是数值类型: {type(point.value)}")

        if point.value < 0 and point.code not in ["CN_M2", "SHIBOR", "LPR"]:
            # 某些指标允许负值
            pass

        if not isinstance(point.observed_at, date):
            raise DataValidationError(f"观测日期必须是 date 类型: {type(point.observed_at)}")

    def _sort_and_deduplicate(
        self,
        data_points: list[MacroDataPoint]
    ) -> list[MacroDataPoint]:
        """
        排序并去重

        Args:
            data_points: 原始数据点列表

        Returns:
            List[MacroDataPoint]: 处理后的数据点列表
        """
        # 按日期排序
        sorted_points = sorted(data_points, key=lambda x: x.observed_at)

        # 去重（保留最新的）
        seen = {}
        for point in sorted_points:
            key = (point.code, point.observed_at)
            if key not in seen:
                seen[key] = point

        return list(seen.values())
