"""
Macro Data Provider Implementation for Regime Module.

Infrastructure 层实现 Domain 层定义的 MacroDataProviderProtocol。

通过延迟导入 macro 模块的方式，实现模块间的解耦。
Regime 模块不再直接导入 macro 模块的 repository，而是通过此适配器访问数据。

IMPORTANT:
    - 这是 Infrastructure 层，可以导入 Django ORM 和其他模块
    - 使用延迟导入避免循环依赖
    - 所有数据转换都在此层完成
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from ..domain.protocols import (
    MacroDataProviderProtocol,
    DataSourceConfigProtocol,
    MacroIndicatorValue,
    IndicatorSeries,
)

logger = logging.getLogger(__name__)


@dataclass
class DjangoDataSourceConfig:
    """Django 实现的数据源配置"""

    _growth_indicator: str = "PMI"
    _inflation_indicator: str = "CPI"
    _use_kalman: bool = True
    _kalman_params: dict = None

    def __init__(self):
        self._kalman_params = {
            "observation_noise": 1.0,
            "process_noise": 0.1,
        }

    def get_growth_indicator(self) -> str:
        return self._growth_indicator

    def get_inflation_indicator(self) -> str:
        return self._inflation_indicator

    def get_use_kalman_filter(self) -> bool:
        return self._use_kalman

    def get_kalman_params(self) -> dict:
        return self._kalman_params


class DjangoMacroDataProvider(MacroDataProviderProtocol):
    """
    Django ORM 实现的宏观数据提供者

    通过延迟导入 DjangoMacroRepository 访问 macro 模块数据。
    这是 regime 模块访问宏观数据的唯一入口点。

    Example:
        >>> provider = DjangoMacroDataProvider()
        >>> pmi_value = provider.get_indicator_value("PMI")
    """

    def __init__(self, config: Optional[DataSourceConfigProtocol] = None):
        """
        初始化提供者

        Args:
            config: 数据源配置 (可选，默认使用 DjangoDataSourceConfig)
        """
        self._config = config or DjangoDataSourceConfig()
        self._repository = None  # 延迟初始化

    def _get_repository(self):
        """
        延迟获取 macro repository

        使用延迟导入避免循环依赖。
        只有在实际访问数据时才导入 macro 模块。
        """
        if self._repository is None:
            # 延迟导入: 只有在运行时才导入，避免模块加载时的循环依赖
            from apps.macro.infrastructure.repositories import DjangoMacroRepository
            self._repository = DjangoMacroRepository()
        return self._repository

    def get_indicator_value(
        self,
        indicator_code: str,
        as_of_date: Optional[date] = None
    ) -> Optional[MacroIndicatorValue]:
        """
        获取指定指标的值

        Args:
            indicator_code: 指标代码
            as_of_date: 截止日期

        Returns:
            MacroIndicatorValue 或 None
        """
        try:
            repo = self._get_repository()

            # 获取最新或指定日期的数据
            if as_of_date:
                observations = repo.get_observations_for_period(
                    indicator_code=indicator_code,
                    start_date=as_of_date,
                    end_date=as_of_date
                )
                if observations:
                    obs = observations[0]
                    return MacroIndicatorValue(
                        indicator_code=indicator_code,
                        value=float(obs.value),
                        observed_at=obs.observed_at,
                        published_at=obs.published_at,
                        unit=getattr(obs, 'unit', None)
                    )
            else:
                # 获取最新值
                obs = repo.get_latest_observation(indicator_code)
                if obs:
                    return MacroIndicatorValue(
                        indicator_code=indicator_code,
                        value=float(obs.value),
                        observed_at=obs.observed_at,
                        published_at=obs.published_at,
                        unit=getattr(obs, 'unit', None)
                    )

            return None

        except Exception as e:
            logger.error(f"Error getting indicator value for {indicator_code}: {e}")
            return None

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
            IndicatorSeries 或 None
        """
        try:
            repo = self._get_repository()

            # 获取历史数据
            observations = repo.get_recent_observations(
                indicator_code=indicator_code,
                limit=lookback_periods
            )

            if not observations:
                return None

            values = []
            dates = []
            for obs in reversed(observations):  # 按时间正序排列
                values.append(float(obs.value))
                dates.append(obs.observed_at)

            return IndicatorSeries(
                indicator_code=indicator_code,
                values=values,
                dates=dates
            )

        except Exception as e:
            logger.error(f"Error getting indicator series for {indicator_code}: {e}")
            return None

    def get_growth_series(
        self,
        indicator_code: str,
        end_date: date,
        lookback_periods: int = 24
    ) -> List[float]:
        """
        获取增长指标序列

        Args:
            indicator_code: 增长指标代码
            end_date: 截止日期
            lookback_periods: 回溯期数

        Returns:
            增长值序列
        """
        series = self.get_indicator_series(indicator_code, end_date, lookback_periods)
        return series.values if series else []

    def get_inflation_series(
        self,
        indicator_code: str,
        end_date: date,
        lookback_periods: int = 24
    ) -> List[float]:
        """
        获取通胀指标序列

        Args:
            indicator_code: 通胀指标代码
            end_date: 截止日期
            lookback_periods: 回溯期数

        Returns:
            通胀值序列
        """
        series = self.get_indicator_series(indicator_code, end_date, lookback_periods)
        return series.values if series else []

    def get_latest_observation_date(self, indicator_code: str) -> Optional[date]:
        """
        获取指定指标的最新观测日期

        Args:
            indicator_code: 指标代码

        Returns:
            最新观测日期或 None
        """
        try:
            repo = self._get_repository()
            return repo.get_latest_observation_date(indicator_code)
        except Exception as e:
            logger.error(f"Error getting latest observation date for {indicator_code}: {e}")
            return None


# 全局单例 (可选)
_default_provider: Optional[DjangoMacroDataProvider] = None
_default_config: Optional[DjangoDataSourceConfig] = None


def get_default_macro_data_provider() -> DjangoMacroDataProvider:
    """
    获取默认的宏观数据提供者单例

    Returns:
        DjangoMacroDataProvider 实例
    """
    global _default_provider
    if _default_provider is None:
        _default_provider = DjangoMacroDataProvider()
    return _default_provider


def get_default_data_source_config() -> DjangoDataSourceConfig:
    """
    获取默认的数据源配置单例

    Returns:
        DjangoDataSourceConfig 实例
    """
    global _default_config
    if _default_config is None:
        _default_config = DjangoDataSourceConfig()
    return _default_config


# ============================================================================
# Repository Adapter
# ============================================================================

class MacroRepositoryAdapter:
    """
    宏观数据仓库适配器

    重构说明 (2026-03-11):
    - 将 MacroDataProviderProtocol 接口适配为 Repository 接口
    - 供 CalculateRegimeV2UseCase 使用
    - 隐藏 Provider 与 Repository 的差异

    This adapter allows the use case to work with a provider instance
    without knowing the underlying implementation.
    """

    def __init__(self, provider: Optional[MacroDataProviderProtocol] = None):
        """
        初始化适配器

        Args:
            provider: 宏观数据提供者 (可选，默认使用全局单例)
        """
        self._provider = provider or get_default_macro_data_provider()

    def get_observations_for_period(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> List:
        """
        获取指定时间段的观测数据

        将 Provider 接口适配为 Repository 接口

        Args:
            indicator_code: 指标代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            观测数据列表
        """
        from dataclasses import dataclass as dc

        @dc
        class ObservationAdapter:
            """观测数据适配器"""
            indicator_code: str
            value: float
            observed_at: date
            published_at: Optional[date]
            unit: Optional[str]

        result = self._provider.get_indicator_value(indicator_code, end_date)
        if result:
            return [ObservationAdapter(
                indicator_code=result.indicator_code,
                value=result.value,
                observed_at=result.observed_at,
                published_at=result.published_at,
                unit=result.unit
            )]
        return []

    def get_latest_observation(self, indicator_code: str):
        """
        获取最新观测数据

        将 Provider 接口适配为 Repository 接口

        Args:
            indicator_code: 指标代码

        Returns:
            观测数据或 None
        """
        from dataclasses import dataclass as dc

        @dc
        class ObservationAdapter:
            """观测数据适配器"""
            indicator_code: str
            value: float
            observed_at: date
            published_at: Optional[date]
            unit: Optional[str]

        result = self._provider.get_indicator_value(indicator_code)
        if result:
            return ObservationAdapter(
                indicator_code=result.indicator_code,
                value=result.value,
                observed_at=result.observed_at,
                published_at=result.published_at,
                unit=result.unit
            )
        return None

    def get_recent_observations(
        self,
        indicator_code: str,
        limit: int = 24
    ) -> List:
        """
        获取最近的观测数据序列

        将 Provider 接口适配为 Repository 接口

        Args:
            indicator_code: 指标代码
            limit: 返回数量限制

        Returns:
            观测数据列表
        """
        from dataclasses import dataclass as dc

        @dc
        class ObservationAdapter:
            """观测数据适配器"""
            indicator_code: str
            value: float
            observed_at: date
            published_at: Optional[date]
            unit: Optional[str]

        series = self._provider.get_indicator_series(
            indicator_code=indicator_code,
            end_date=date.today(),
            lookback_periods=limit
        )

        if not series:
            return []

        adapters = []
        for i, (val, obs_date) in enumerate(zip(series.values, series.dates)):
            adapters.append(ObservationAdapter(
                indicator_code=indicator_code,
                value=val,
                observed_at=obs_date,
                published_at=None,
                unit=None
            ))
        return adapters

    def get_latest_observation_date(self, indicator_code: str) -> Optional[date]:
        """
        获取最新观测日期

        Args:
            indicator_code: 指标代码

        Returns:
            最新观测日期或 None
        """
        return self._provider.get_latest_observation_date(indicator_code)
