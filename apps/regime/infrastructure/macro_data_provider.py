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
    DataSourceConfigProtocol,
    IndicatorSeries,
    MacroDataProviderProtocol,
    MacroIndicatorValue,
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

    def __init__(self, config: DataSourceConfigProtocol | None = None):
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
        as_of_date: date | None = None
    ) -> MacroIndicatorValue | None:
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
    ) -> IndicatorSeries | None:
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
    ) -> list[float]:
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
    ) -> list[float]:
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

    def get_latest_observation_date(self, indicator_code: str) -> date | None:
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
_default_provider: DjangoMacroDataProvider | None = None
_default_config: DjangoDataSourceConfig | None = None


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

    GROWTH_INDICATORS = {
        "PMI": "CN_PMI",
        "工业增加值": "CN_VALUE_ADDED",
        "社会消费品零售": "CN_RETAIL_SALES",
    }

    INFLATION_INDICATORS = {
        "CPI": "CN_CPI_NATIONAL_YOY",
        "PPI": "CN_PPI",
        "GDP平减指数": "CN_GDP_DEFLATOR",
    }

    def __init__(self, provider: MacroDataProviderProtocol | None = None):
        """
        初始化适配器

        Args:
            provider: 宏观数据提供者 (可选，默认使用全局单例)
        """
        self._provider = provider or get_default_macro_data_provider()
        self._repository = None

    def _get_repository(self):
        if self._repository is None:
            from apps.macro.infrastructure.repositories import DjangoMacroRepository

            self._repository = DjangoMacroRepository()
        return self._repository

    def get_observations_for_period(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list:
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
        return self._get_repository().get_observations_for_period(
            indicator_code=indicator_code,
            start_date=start_date,
            end_date=end_date,
        )

    def get_latest_observation(self, code: str, before_date: date | None = None):
        """获取最新观测数据。"""
        return self._get_repository().get_latest_observation(
            code=code,
            before_date=before_date,
        )

    def get_recent_observations(
        self,
        indicator_code: str,
        limit: int = 24
    ) -> list:
        """
        获取最近的观测数据序列

        将 Provider 接口适配为 Repository 接口

        Args:
            indicator_code: 指标代码
            limit: 返回数量限制

        Returns:
            观测数据列表
        """
        return self._get_repository().get_recent_observations(
            indicator_code=indicator_code,
            limit=limit,
        )

    def get_latest_observation_date(self, indicator_code: str) -> date | None:
        """
        获取最新观测日期

        Args:
            indicator_code: 指标代码

        Returns:
            最新观测日期或 None
        """
        return self._get_repository().get_latest_observation_date(indicator_code)

    def get_by_code_and_date(self, code: str, observed_at: date):
        return self._get_repository().get_by_code_and_date(
            code=code,
            observed_at=observed_at,
        )

    def get_growth_series(
        self,
        indicator_code: str = "PMI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ):
        return self._get_repository().get_growth_series(
            indicator_code=indicator_code,
            end_date=end_date or date.today(),
            use_pit=use_pit,
            source=source,
        )

    def get_growth_series_full(
        self,
        indicator_code: str = "PMI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ):
        return self._get_repository().get_growth_series_full(
            indicator_code=indicator_code,
            end_date=end_date or date.today(),
            use_pit=use_pit,
            source=source,
        )

    def get_inflation_series(
        self,
        indicator_code: str = "CPI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ):
        return self._get_repository().get_inflation_series(
            indicator_code=indicator_code,
            end_date=end_date or date.today(),
            use_pit=use_pit,
            source=source,
        )

    def get_inflation_series_full(
        self,
        indicator_code: str = "CPI",
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ):
        return self._get_repository().get_inflation_series_full(
            indicator_code=indicator_code,
            end_date=end_date or date.today(),
            use_pit=use_pit,
            source=source,
        )

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        return self._get_repository().get_available_dates(
            codes=codes,
            start_date=start_date,
            end_date=end_date,
        )

    def __getattr__(self, item):
        return getattr(self._get_repository(), item)
