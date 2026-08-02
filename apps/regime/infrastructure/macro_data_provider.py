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
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from apps.data_center.application.public import (
    get_macro_fact_series,
    get_macro_indicator_catalog,
    is_direct_macro_input_allowed,
    list_macro_indicator_codes,
)

from ..domain.protocols import (
    DataSourceConfigProtocol,
    IndicatorSeries,
    MacroDataProviderProtocol,
    MacroIndicator,
    MacroIndicatorValue,
    PeriodType,
)

logger = logging.getLogger(__name__)


@dataclass
class DjangoDataSourceConfig:
    """Django 实现的数据源配置"""

    _growth_indicator: str = "PMI"
    _inflation_indicator: str = "CPI"
    _use_kalman: bool = True
    _kalman_params: dict[str, float] = field(
        default_factory=lambda: {
            "observation_noise": 1.0,
            "process_noise": 0.1,
        }
    )

    def get_growth_indicator(self) -> str:
        return self._growth_indicator

    def get_inflation_indicator(self) -> str:
        return self._inflation_indicator

    def get_use_kalman_filter(self) -> bool:
        return self._use_kalman

    def get_kalman_params(self) -> dict[str, float]:
        return dict(self._kalman_params)


class DataCenterMacroRepositoryAdapter:
    """
    Bridge the legacy regime macro repository contract onto data_center facts.

    The regime module still expects the old macro repository interface
    (`get_growth_series`, `get_latest_observation`, etc.). This adapter keeps
    that interface stable while sourcing all reads from `apps.data_center`.
    """

    GROWTH_INDICATORS: dict[str, str] = {
        "PMI": "CN_PMI",
        "工业增加值": "CN_VALUE_ADDED",
        "社会消费品零售": "CN_RETAIL_SALES",
    }

    INFLATION_INDICATORS: dict[str, str] = {
        "CPI": "CN_CPI_NATIONAL_YOY",
        "PPI": "CN_PPI",
        "GDP平减指数": "CN_GDP_DEFLATOR",
    }

    @staticmethod
    def _normalize_cpi_value(code: str, value: float) -> float:
        """
        Normalize CPI readings to percentage points.

        - `CN_CPI` is index-style (e.g. 100.8) and should become `0.8`
        - `CN_CPI_NATIONAL_YOY` is canonicalized on ingestion and already uses
          percentage points; source-specific scaling belongs in Data Center unit
          rules, never in this consumer adapter.
        """
        if code == "CN_CPI":
            return float(value) - 100.0
        return float(value)

    def _get_default_period_type(self, indicator_code: str) -> str:
        """Read the current catalog period type without retaining stale governance state."""

        catalog = get_macro_indicator_catalog(indicator_code)
        return str(catalog.get("default_period_type") or "D")

    def _get_catalog_extra(self, indicator_code: str) -> dict[str, Any]:
        """Read live catalog governance metadata for the requested indicator."""

        catalog = get_macro_indicator_catalog(indicator_code)
        return dict(catalog.get("extra") or {})

    def _is_regime_direct_input_allowed(self, indicator_code: str) -> bool:
        return bool(
            is_direct_macro_input_allowed(
                self._get_catalog_extra(indicator_code),
                consumer="regime",
            )
        )

    def _to_macro_indicator(self, fact: dict[str, Any]) -> MacroIndicator:
        extra: dict[str, Any] = dict(fact.get("extra") or {})
        indicator_code = str(fact["indicator_code"])
        reporting_period = date.fromisoformat(str(fact["reporting_period"]))
        published_value = fact.get("published_at")
        published_at = date.fromisoformat(str(published_value)) if published_value else None
        period_type_value = extra.get("period_type") or self._get_default_period_type(
            indicator_code
        )
        try:
            period_type = PeriodType(period_type_value)
        except (ValueError, KeyError):
            period_type = PeriodType.DAY

        return MacroIndicator(
            code=indicator_code,
            value=float(fact["value"]),
            reporting_period=reporting_period,
            period_type=period_type,
            unit=str(fact.get("unit") or ""),
            original_unit=str(extra.get("original_unit") or fact.get("unit") or ""),
            published_at=published_at,
            source=str(fact.get("source") or "unknown"),
        )

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        rows = get_macro_fact_series(
            code,
            start=start_date,
            end=end_date,
            limit=500,
            use_pit=use_pit,
            source=source,
        )
        return [self._to_macro_indicator(row) for row in rows]

    def get_observations_for_period(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroIndicator]:
        return self.get_series(
            code=indicator_code,
            start_date=start_date,
            end_date=end_date,
        )

    def get_recent_observations(
        self,
        indicator_code: str,
        limit: int = 24,
    ) -> list[MacroIndicator]:
        rows = get_macro_fact_series(indicator_code, limit=max(limit, 1))
        return [self._to_macro_indicator(row) for row in reversed(rows[-limit:])]

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: date | None = None,
    ) -> date | None:
        observations = self.get_series(
            code=code,
            end_date=as_of_date,
            use_pit=as_of_date is not None,
        )
        return observations[-1].reporting_period if observations else None

    def get_latest_observation(
        self,
        code: str,
        before_date: date | None = None,
    ) -> MacroIndicator | None:
        end_date = before_date - date.resolution if before_date else None
        observations = self.get_series(code=code, end_date=end_date, use_pit=end_date is not None)
        return observations[-1] if observations else None

    def get_by_code_and_date(self, code: str, observed_at: date) -> MacroIndicator | None:
        observations = self.get_series(code=code, start_date=observed_at, end_date=observed_at)
        return observations[-1] if observations else None

    def get_growth_series(
        self,
        indicator_code: str = "PMI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[float]:
        return [
            indicator.value
            for indicator in self.get_growth_series_full(
                indicator_code=indicator_code,
                start_date=start_date,
                end_date=end_date,
                use_pit=use_pit,
                source=source,
            )
        ]

    def get_growth_series_full(
        self,
        indicator_code: str = "PMI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        code = self.GROWTH_INDICATORS.get(indicator_code, indicator_code)
        if not self._is_regime_direct_input_allowed(code):
            logger.warning(
                "Blocked regime direct input for %s because catalog policy requires derivation first",
                code,
            )
            return []
        return self.get_series(
            code=code,
            start_date=start_date,
            end_date=end_date,
            use_pit=use_pit,
            source=source,
        )

    def get_inflation_series(
        self,
        indicator_code: str = "CPI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[float]:
        return [
            indicator.value
            for indicator in self.get_inflation_series_full(
                indicator_code=indicator_code,
                start_date=start_date,
                end_date=end_date,
                use_pit=use_pit,
                source=source,
            )
        ]

    def get_inflation_series_full(
        self,
        indicator_code: str = "CPI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        code = self.INFLATION_INDICATORS.get(indicator_code, indicator_code)
        if not self._is_regime_direct_input_allowed(code):
            logger.warning(
                "Blocked regime direct input for %s because catalog policy requires derivation first",
                code,
            )
            return []
        indicators = self.get_series(
            code=code,
            start_date=start_date,
            end_date=end_date,
            use_pit=use_pit,
            source=source,
        )

        if indicator_code == "CPI" and not indicators and code == "CN_CPI_NATIONAL_YOY":
            code = "CN_CPI"
            indicators = self.get_series(
                code=code,
                start_date=start_date,
                end_date=end_date,
                use_pit=use_pit,
                source=source,
            )

        if indicator_code != "CPI":
            return indicators

        normalized: list[MacroIndicator] = []
        for indicator in indicators:
            normalized.append(
                MacroIndicator(
                    code=indicator.code,
                    value=self._normalize_cpi_value(code, indicator.value),
                    reporting_period=indicator.reporting_period,
                    period_type=indicator.period_type,
                    unit="%",
                    original_unit=indicator.original_unit,
                    published_at=indicator.published_at,
                    source=indicator.source,
                )
            )
        return normalized

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        rows: list[dict[str, Any]] = []
        if codes:
            for code in codes:
                rows.extend(
                    get_macro_fact_series(
                        code,
                        start=start_date,
                        end=end_date,
                        limit=2000,
                        use_pit=end_date is not None,
                    )
                )
        else:
            # The legacy protocol asks for all dates; use the active catalog as
            # the bounded source list rather than querying the ORM here.
            for code in list_macro_indicator_codes():
                rows.extend(
                    get_macro_fact_series(
                        code,
                        start=start_date,
                        end=end_date,
                        limit=2000,
                        use_pit=end_date is not None,
                    )
                )
        return sorted(
            {
                date.fromisoformat(str(row["reporting_period"]))
                for row in rows
            }
        )



class DjangoMacroDataProvider:
    """
    Django ORM 实现的宏观数据提供者

    通过延迟导入 DataCenterMacroRepository 访问 macro 模块数据。
    这是 regime 模块访问宏观数据的唯一入口点。

    Example:
        >>> provider = DjangoMacroDataProvider()
        >>> pmi_value = provider.get_indicator_value("PMI")
    """

    def __init__(self, config: DataSourceConfigProtocol | None = None) -> None:
        """
        初始化提供者

        Args:
            config: 数据源配置 (可选，默认使用 DjangoDataSourceConfig)
        """
        self._config = config or DjangoDataSourceConfig()
        self._repository: DataCenterMacroRepositoryAdapter | None = None

    def _get_repository(self) -> DataCenterMacroRepositoryAdapter:
        """
        延迟获取 regime macro repository

        所有读取统一走 data_center 宏观事实表，避免 regime 再直接依赖
        legacy macro ORM 表。
        """
        if self._repository is None:
            self._repository = DataCenterMacroRepositoryAdapter()
        return self._repository

    def get_indicator_value(
        self, indicator_code: str, as_of_date: date | None = None
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
                    indicator_code=indicator_code, start_date=as_of_date, end_date=as_of_date
                )
                if observations:
                    obs = observations[0]
                    return MacroIndicatorValue(
                        indicator_code=indicator_code,
                        value=float(obs.value),
                        observed_at=obs.observed_at,
                        published_at=obs.published_at,
                        unit=getattr(obs, "unit", None),
                    )
            else:
                # 获取最新值
                latest_observation = repo.get_latest_observation(indicator_code)
                if latest_observation:
                    return MacroIndicatorValue(
                        indicator_code=indicator_code,
                        value=float(latest_observation.value),
                        observed_at=latest_observation.observed_at,
                        published_at=latest_observation.published_at,
                        unit=getattr(latest_observation, "unit", None),
                    )

            return None

        except Exception as e:
            logger.error(f"Error getting indicator value for {indicator_code}: {e}")
            return None

    def get_indicator_series(
        self, indicator_code: str, end_date: date, lookback_periods: int = 24
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

            observations = repo.get_series(
                code=indicator_code,
                end_date=end_date,
            )
            observations = observations[-lookback_periods:]

            if not observations:
                return None

            values: list[float] = []
            dates: list[date] = []
            for obs in reversed(observations):  # 按时间正序排列
                values.append(float(obs.value))
                dates.append(obs.observed_at)

            return IndicatorSeries(indicator_code=indicator_code, values=values, dates=dates)

        except Exception as e:
            logger.error(f"Error getting indicator series for {indicator_code}: {e}")
            return None

    def get_growth_series(
        self, indicator_code: str, end_date: date, lookback_periods: int = 24
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
        self, indicator_code: str, end_date: date, lookback_periods: int = 24
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

    def get_latest_observation_date(
        self,
        indicator_code: str,
        as_of_date: date | None = None,
    ) -> date | None:
        """
        获取指定指标的最新观测日期

        Args:
            indicator_code: 指标代码

        Returns:
            最新观测日期或 None
        """
        try:
            repo = self._get_repository()
            return repo.get_latest_observation_date(
                indicator_code,
                as_of_date=as_of_date,
            )
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

    GROWTH_INDICATORS: dict[str, str] = {
        "PMI": "CN_PMI",
        "工业增加值": "CN_VALUE_ADDED",
        "社会消费品零售": "CN_RETAIL_SALES",
    }

    INFLATION_INDICATORS: dict[str, str] = {
        "CPI": "CN_CPI_NATIONAL_YOY",
        "PPI": "CN_PPI",
        "GDP平减指数": "CN_GDP_DEFLATOR",
    }

    def __init__(self, provider: MacroDataProviderProtocol | None = None) -> None:
        """
        初始化适配器

        Args:
            provider: 宏观数据提供者 (可选，默认使用全局单例)
        """
        self._provider = provider or get_default_macro_data_provider()
        self._repository: DataCenterMacroRepositoryAdapter | None = None

    def _get_repository(self) -> DataCenterMacroRepositoryAdapter:
        if self._repository is None:
            repository_factory = getattr(self._provider, "_get_repository", None)
            if callable(repository_factory):
                self._repository = cast(
                    DataCenterMacroRepositoryAdapter,
                    repository_factory(),
                )
            else:
                self._repository = DataCenterMacroRepositoryAdapter()
        return self._repository

    def get_observations_for_period(
        self, indicator_code: str, start_date: date, end_date: date
    ) -> list[MacroIndicator]:
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

    def get_latest_observation(
        self, code: str, before_date: date | None = None
    ) -> MacroIndicator | None:
        """获取最新观测数据。"""
        return self._get_repository().get_latest_observation(
            code=code,
            before_date=before_date,
        )

    def get_recent_observations(self, indicator_code: str, limit: int = 24) -> list[MacroIndicator]:
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

    def get_latest_observation_date(
        self,
        indicator_code: str,
        as_of_date: date | None = None,
    ) -> date | None:
        """
        获取最新观测日期

        Args:
            indicator_code: 指标代码

        Returns:
            最新观测日期或 None
        """
        return self._get_repository().get_latest_observation_date(
            indicator_code,
            as_of_date=as_of_date,
        )

    def get_by_code_and_date(self, code: str, observed_at: date) -> MacroIndicator | None:
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
    ) -> list[float]:
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
    ) -> list[MacroIndicator]:
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
    ) -> list[float]:
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
    ) -> list[MacroIndicator]:
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

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get_repository(), item)
