"""
Protocol Interfaces for Regime Module.

定义 regime 模块依赖的外部接口，实现依赖反转。

这些 Protocol 定义了 regime 模块需要从其他模块获取的数据接口。
通过依赖注入方式解耦，避免直接导入 macro 模块。

IMPORTANT:
    - Domain 层只能定义 Protocol 接口，不能导入 Django ORM 或其他外部依赖
    - 具体实现在 Infrastructure 层提供
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class MacroIndicatorValue:
    """宏观指标值"""
    indicator_code: str
    value: float
    observed_at: date
    published_at: Optional[date]
    unit: Optional[str]


@dataclass(frozen=True)
class IndicatorSeries:
    """指标时间序列"""
    indicator_code: str
    values: List[float]
    dates: List[date]


class MacroDataProviderProtocol(Protocol):
    """
    宏观数据提供者协议

    定义 regime 模块从 macro 模块获取数据的接口。

    Usage:
        # 在 Application 层注入实现
        macro_provider = DjangoMacroDataProvider()
        use_case = CalculateRegimeUseCase(macro_data_provider=macro_provider)
    """

    def get_indicator_value(
        self,
        indicator_code: str,
        as_of_date: Optional[date] = None
    ) -> Optional[MacroIndicatorValue]:
        """
        获取指定指标的最新值

        Args:
            indicator_code: 指标代码 (如 PMI, CPI)
            as_of_date: 截止日期 (None 表示最新)

        Returns:
            指标值，如果不存在返回 None
        """
        ...

    def get_indicator_series(
        self,
        indicator_code: str,
        end_date: date,
        lookback_periods: int = 24
    ) -> Optional[IndicatorSeries]:
        """
        获取指标的历史序列

        Args:
            indicator_code: 指标代码
            end_date: 截止日期
            lookback_periods: 回溯期数

        Returns:
            指标序列，如果不存在返回 None
        """
        ...

    def get_growth_series(
        self,
        indicator_code: str,
        end_date: date,
        lookback_periods: int = 24
    ) -> List[float]:
        """
        获取增长指标序列 (用于 Kalman 滤波)

        Args:
            indicator_code: 增长指标代码 (如 PMI)
            end_date: 截止日期
            lookback_periods: 回溯期数

        Returns:
            增长值序列
        """
        ...

    def get_inflation_series(
        self,
        indicator_code: str,
        end_date: date,
        lookback_periods: int = 24
    ) -> List[float]:
        """
        获取通胀指标序列 (用于 Kalman 滤波)

        Args:
            indicator_code: 通胀指标代码 (如 CPI)
            end_date: 截止日期
            lookback_periods: 回溯期数

        Returns:
            通胀值序列
        """
        ...

    def get_latest_observation_date(self, indicator_code: str) -> Optional[date]:
        """
        获取指定指标的最新观测日期

        Args:
            indicator_code: 指标代码

        Returns:
            最新观测日期，如果不存在返回 None
        """
        ...


class DataSourceConfigProtocol(Protocol):
    """
    数据源配置协议

    定义 regime 模块获取数据源配置的接口。
    """

    def get_growth_indicator(self) -> str:
        """获取增长指标代码"""
        ...

    def get_inflation_indicator(self) -> str:
        """获取通胀指标代码"""
        ...

    def get_use_kalman_filter(self) -> bool:
        """是否使用 Kalman 滤波"""
        ...

    def get_kalman_params(self) -> dict:
        """获取 Kalman 滤波参数"""
        ...
