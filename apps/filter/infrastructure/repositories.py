"""
Repositories for Filter Operations.

Data access layer for filter results and configurations.
"""

import math
from datetime import date
from decimal import Decimal
from importlib import import_module
from typing import Any, Protocol, TypedDict, cast

from django.db import transaction

from apps.data_center.domain.rules import MacroFactPreferenceCandidate
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    select_macro_fact_series,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.filter.domain.entities import (
    FilterResult,
    FilterSeries,
    FilterType,
    KalmanFilterParams,
    KalmanFilterState,
)
from shared.infrastructure.kalman_filter import LocalLinearTrendFilter

from .models import FilterConfig, FilterResultModel, KalmanStateModel


class FilterRepositoryProtocol(Protocol):
    """滤波器仓储接口"""

    def save_filter_results(self, series: FilterSeries) -> None:
        """保存滤波结果"""
        ...

    def get_filter_results(
        self,
        indicator_code: str,
        filter_type: FilterType,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FilterResult]:
        """获取滤波结果"""
        ...

    def get_latest_kalman_state(self, indicator_code: str) -> KalmanFilterState | None:
        """获取最新的 Kalman 状态"""
        ...

    def save_kalman_state(
        self,
        indicator_code: str,
        state: KalmanFilterState,
        params: dict[str, object],
    ) -> None:
        """保存 Kalman 状态"""
        ...

    def update_filter_config(
        self, indicator_code: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """更新滤波器配置"""
        ...

    def delete_filter_config(self, indicator_code: str) -> bool:
        """删除滤波器配置"""
        ...


class HPFilterCallable(Protocol):
    """Typed boundary for statsmodels' HP filter function."""

    def __call__(
        self,
        values: list[float],
        *,
        lamb: float,
    ) -> tuple[Any, Any]: ...


class MacroIndicatorPoint(TypedDict):
    """Validated macro observation consumed by Filter application use cases."""

    date: date
    value: float


class DjangoFilterRepository:
    """Django ORM 滤波器仓储实现"""

    def save_filter_results(self, series: FilterSeries) -> None:
        """
        保存滤波结果

        使用 upsert 语义：如果记录存在则更新，否则创建。
        """
        with transaction.atomic():
            # 先删除旧的相同类型结果
            FilterResultModel._default_manager.filter(
                indicator_code=series.indicator_code, filter_type=series.filter_type.value
            ).delete()

            # 批量创建新结果
            results_to_create: list[FilterResultModel] = []
            for r in series.results:
                results_to_create.append(
                    FilterResultModel(
                        indicator_code=series.indicator_code,
                        date=r.date,
                        filter_type=series.filter_type.value,
                        params=series.params,
                        original_value=Decimal(str(r.original_value)),
                        filtered_value=Decimal(str(r.filtered_value)),
                        cycle_value=Decimal(str(r.original_value - r.filtered_value)),
                        trend_slope=Decimal(str(r.slope)) if r.slope is not None else None,
                    )
                )

            FilterResultModel._default_manager.bulk_create(results_to_create, batch_size=500)

    def get_filter_results(
        self,
        indicator_code: str,
        filter_type: FilterType,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FilterResult]:
        """获取滤波结果"""
        queryset = FilterResultModel._default_manager.filter(
            indicator_code=indicator_code, filter_type=filter_type.value
        )

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        queryset = queryset.order_by("date")

        return [
            FilterResult(
                date=r.date,
                original_value=float(r.original_value),
                filtered_value=float(r.filtered_value),
                trend=float(r.filtered_value),
                slope=float(r.trend_slope) if r.trend_slope is not None else None,
            )
            for r in queryset
        ]

    def get_latest_kalman_state(self, indicator_code: str) -> KalmanFilterState | None:
        """获取最新的 Kalman 状态"""
        try:
            model = KalmanStateModel._default_manager.get(indicator_code=indicator_code)
            return KalmanFilterState(
                level=float(model.level),
                slope=float(model.slope),
                level_variance=float(model.level_variance),
                slope_variance=float(model.slope_variance),
                level_slope_cov=float(model.level_slope_cov),
                updated_at=model.last_observed_date,
            )
        except KalmanStateModel.DoesNotExist:
            return None

    def save_kalman_state(
        self,
        indicator_code: str,
        state: KalmanFilterState,
        params: dict[str, object],
    ) -> None:
        """保存 Kalman 状态"""
        with transaction.atomic():
            KalmanStateModel._default_manager.filter(indicator_code=indicator_code).delete()
            KalmanStateModel.from_domain_state(state, indicator_code, params).save()

    def get_filter_config(self, indicator_code: str) -> dict[str, object]:
        """获取滤波器配置"""
        try:
            config = FilterConfig._default_manager.get(indicator_code=indicator_code)
            return {
                "hp_enabled": config.hp_enabled,
                "hp_lambda": float(config.hp_lambda),
                "kalman_enabled": config.kalman_enabled,
                "kalman_level_variance": float(config.kalman_level_variance),
                "kalman_slope_variance": float(config.kalman_slope_variance),
                "kalman_observation_variance": float(config.kalman_observation_variance),
            }
        except FilterConfig.DoesNotExist:
            # 返回默认配置
            return {
                "hp_enabled": True,
                "hp_lambda": 129600.0,
                "kalman_enabled": True,
                "kalman_level_variance": 0.05,
                "kalman_slope_variance": 0.005,
                "kalman_observation_variance": 0.5,
            }

    def update_filter_config(
        self, indicator_code: str, payload: dict[str, object]
    ) -> dict[str, object]:
        """Update or create one filter config by indicator code."""
        config, _created = FilterConfig._default_manager.get_or_create(
            indicator_code=indicator_code,
        )
        field_names = (
            "hp_enabled",
            "hp_lambda",
            "kalman_enabled",
            "kalman_level_variance",
            "kalman_slope_variance",
            "kalman_observation_variance",
            "description",
        )
        for field_name in field_names:
            if field_name in payload:
                setattr(config, field_name, payload[field_name])
        config.full_clean()
        config.save()
        result = self.get_filter_config(indicator_code)
        result["indicator_code"] = indicator_code
        result["description"] = config.description
        return result

    def delete_filter_config(self, indicator_code: str) -> bool:
        """Delete one persisted filter config override by indicator code."""
        deleted_count, _detail = FilterConfig._default_manager.filter(
            indicator_code=indicator_code,
        ).delete()
        return deleted_count > 0

    def get_macro_indicator_data(
        self,
        indicator_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 200,
    ) -> list[MacroIndicatorPoint]:
        """
        获取宏观数据

        Args:
            indicator_code: 指标代码
            start_date: 开始日期
            end_date: 结束日期
            limit: 最大记录数

        Returns:
            List[Dict]: 日期和值的字典列表
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
            raise ValueError("limit must be an integer from 1 to 2000")
        normalized_code = indicator_code.strip()
        if not normalized_code:
            raise ValueError("indicator_code cannot be empty")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date cannot be after end_date")

        queryset = MacroFactModel._default_manager.filter(indicator_code=normalized_code)

        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)

        facts = list(queryset.order_by("-reporting_period", "-id")[: max(limit * 4, limit)])
        catalog = (
            IndicatorCatalogModel._default_manager.filter(code=normalized_code)
            .only("extra")
            .first()
        )
        fact_candidates = [cast(MacroFactPreferenceCandidate, fact) for fact in facts]
        selection = select_macro_fact_series(
            fact_candidates,
            preferred_source=configured_macro_source(catalog.extra if catalog else {}),
        )
        if not selection.is_consistent:
            return []
        selected = selection.facts[-limit:]

        result: list[MacroIndicatorPoint] = []
        for item in selected:
            value = float(item.value)
            if not math.isfinite(value):
                continue
            result.append(
                {
                    "date": item.reporting_period,
                    "value": value,
                }
            )
        return result

    def get_available_indicators(self) -> list[dict[str, str]]:
        """获取可用的指标列表（包含代码和名称）"""
        codes = (
            MacroFactModel._default_manager.values_list("indicator_code", flat=True)
            .distinct()
            .order_by("indicator_code")
        )
        code_list = [str(code).strip() for code in codes if str(code).strip()]
        catalog_map = {
            item.code: item.name_cn
            for item in IndicatorCatalogModel._default_manager.filter(code__in=code_list)
        }

        indicators: list[dict[str, str]] = []
        for code in code_list:
            indicators.append({"code": code, "name": catalog_map.get(code, code)})
        return indicators


class HPFilterAdapter:
    """
    HP 滤波适配器

    使用 statsmodels 实现的 HP 滤波，支持扩张窗口模式。
    """

    def __init__(self) -> None:
        hp_filter_module = import_module("statsmodels.tsa.filters.hp_filter")
        self.hpfilter = cast(HPFilterCallable, hp_filter_module.hpfilter)

    def filter_expanding(self, values: list[float], lamb: float = 129600) -> list[float]:
        """
        扩张窗口 HP 滤波

        Args:
            values: 原始值序列
            lamb: 平滑参数

        Returns:
            List[float]: 趋势序列
        """
        if not math.isfinite(lamb) or lamb < 0:
            raise ValueError("HP lambda must be finite and non-negative")
        if any(not math.isfinite(value) for value in values):
            raise ValueError("HP observations must be finite")
        if len(values) < 4:
            return values.copy()

        trends: list[float] = []

        for i in range(len(values)):
            window = values[: i + 1]

            if len(window) < 4:
                trends.append(values[i])
            else:
                # 调用 statsmodels
                _cycle, trend = self.hpfilter(window, lamb=lamb)
                trends.append(float(trend[-1]))

        return trends


class KalmanFilterAdapter:
    """
    Kalman 滤波适配器

    封装 shared.infrastructure.kalman_filter.LocalLinearTrendFilter
    """

    def __init__(self, params: KalmanFilterParams) -> None:
        self.filter = LocalLinearTrendFilter(
            level_variance=params.level_variance,
            slope_variance=params.slope_variance,
            observation_variance=params.observation_variance,
        )

    def filter_series(
        self, values: list[float], initial_state: KalmanFilterState | None = None
    ) -> tuple[list[float], list[float], KalmanFilterState]:
        """
        对序列进行 Kalman 滤波

        Args:
            values: 观测值序列
            initial_state: 初始状态（可选）

        Returns:
            tuple: (levels, slopes, final_state)
        """
        initial_level = initial_state.level if initial_state else None
        initial_slope = initial_state.slope if initial_state else 0.0

        result = self.filter.filter(
            observations=values,
            initial_level=initial_level,
            initial_slope=initial_slope,
        )

        final_state = KalmanFilterState(
            level=result.final_state.level,
            slope=result.final_state.slope,
            level_variance=result.final_state.level_variance,
            slope_variance=result.final_state.slope_variance,
            level_slope_cov=result.final_state.level_slope_cov,
            updated_at=date.today(),
        )

        return result.filtered_levels, result.filtered_slopes, final_state
