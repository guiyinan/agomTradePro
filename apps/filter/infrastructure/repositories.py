"""
Repositories for Filter Operations.

Data access layer for filter results and configurations.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Protocol

from django.db import transaction
from django.db.models import Q

from apps.filter.domain.entities import (
    FilterResult,
    FilterSeries,
    FilterType,
    HPFilterParams,
    KalmanFilterParams,
    KalmanFilterState,
)
from apps.macro.infrastructure.models import MacroIndicator

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
        end_date: date | None = None
    ) -> list[FilterResult]:
        """获取滤波结果"""
        ...

    def get_latest_kalman_state(
        self,
        indicator_code: str
    ) -> KalmanFilterState | None:
        """获取最新的 Kalman 状态"""
        ...

    def save_kalman_state(
        self,
        indicator_code: str,
        state: KalmanFilterState,
        params: dict
    ) -> None:
        """保存 Kalman 状态"""
        ...


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
                indicator_code=series.indicator_code,
                filter_type=series.filter_type.value
            ).delete()

            # 批量创建新结果
            results_to_create = []
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
                        trend_slope=Decimal(str(r.slope)) if r.slope else None,
                    )
                )

            FilterResultModel._default_manager.bulk_create(results_to_create, batch_size=500)

    def get_filter_results(
        self,
        indicator_code: str,
        filter_type: FilterType,
        start_date: date | None = None,
        end_date: date | None = None
    ) -> list[FilterResult]:
        """获取滤波结果"""
        queryset = FilterResultModel._default_manager.filter(
            indicator_code=indicator_code,
            filter_type=filter_type.value
        )

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)

        queryset = queryset.order_by('date')

        return [
            FilterResult(
                date=r.date,
                original_value=float(r.original_value),
                filtered_value=float(r.filtered_value),
                trend=float(r.filtered_value),
                slope=float(r.trend_slope) if r.trend_slope else None,
            )
            for r in queryset
        ]

    def get_latest_kalman_state(
        self,
        indicator_code: str
    ) -> KalmanFilterState | None:
        """获取最新的 Kalman 状态"""
        try:
            model = KalmanStateModel._default_manager.get(indicator_code=indicator_code)
            return model.to_domain_state()
        except KalmanStateModel.DoesNotExist:
            return None

    def save_kalman_state(
        self,
        indicator_code: str,
        state: KalmanFilterState,
        params: dict
    ) -> None:
        """保存 Kalman 状态"""
        with transaction.atomic():
            KalmanStateModel._default_manager.filter(indicator_code=indicator_code).delete()
            KalmanStateModel.from_domain_state(
                state, indicator_code, params
            ).save()

    def get_filter_config(self, indicator_code: str) -> dict:
        """获取滤波器配置"""
        try:
            config = FilterConfig._default_manager.get(indicator_code=indicator_code)
            return {
                'hp_enabled': config.hp_enabled,
                'hp_lambda': float(config.hp_lambda),
                'kalman_enabled': config.kalman_enabled,
                'kalman_level_variance': float(config.kalman_level_variance),
                'kalman_slope_variance': float(config.kalman_slope_variance),
                'kalman_observation_variance': float(config.kalman_observation_variance),
            }
        except FilterConfig.DoesNotExist:
            # 返回默认配置
            return {
                'hp_enabled': True,
                'hp_lambda': 129600.0,
                'kalman_enabled': True,
                'kalman_level_variance': 0.05,
                'kalman_slope_variance': 0.005,
                'kalman_observation_variance': 0.5,
            }

    def get_macro_indicator_data(
        self,
        indicator_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 200
    ) -> list[dict]:
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
        queryset = MacroIndicator._default_manager.filter(code=indicator_code)

        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)

        queryset = queryset.order_by('-reporting_period')[:limit]

        return [
            {
                'date': item.reporting_period,
                'value': float(item.value),
            }
            for item in reversed(queryset)
        ]

    def get_available_indicators(self) -> list[dict]:
        """获取可用的指标列表（包含代码和名称）"""
        # 常见指标名称映射
        INDICATOR_NAMES = {
            'CN_PMI': 'PMI (制造业采购经理指数)',
            'CN_NON_MAN_PMI': '非制造业PMI',
            'CN_CPI': 'CPI (居民消费价格指数)',
            'CN_CPI_NATIONAL_YOY': 'CPI同比',
            'CN_CPI_NATIONAL_MOM': 'CPI环比',
            'CN_PPI': 'PPI (工业生产者出厂价格指数)',
            'CN_PPI_YOY': 'PPI同比',
            'CN_M2': 'M2 (广义货币供应量)',
            'CN_SHIBOR': 'SHIBOR (上海银行间同业拆放利率)',
            'CN_LPR': 'LPR (贷款市场报价利率)',
            'CN_RRR': 'RRR (存款准备金率)',
            'CN_GDP': 'GDP (国内生产总值)',
            'CN_VALUE_ADDED': '工业增加值',
            'CN_RETAIL_SALES': '社会消费品零售总额',
            'CN_NEW_CREDIT': '新增人民币贷款',
            'CN_RMB_LOAN': '人民币贷款',
            'CN_RMB_DEPOSIT': '人民币存款',
            'CN_EXPORTS': '出口额',
            'CN_IMPORTS': '进口额',
            'CN_TRADE_BALANCE': '贸易差额',
            'CN_FX_RESERVES': '外汇储备',
            'CN_NEW_HOUSE_PRICE': '新建住宅价格指数',
            'CN_OIL_PRICE': '原油价格',
        }

        codes = MacroIndicator._default_manager.values_list('code', flat=True).distinct().order_by('code')

        indicators = []
        for code in codes:
            indicators.append({
                'code': code,
                'name': INDICATOR_NAMES.get(code, code)  # 如果没有映射，使用代码本身
            })
        return indicators


class HPFilterAdapter:
    """
    HP 滤波适配器

    使用 statsmodels 实现的 HP 滤波，支持扩张窗口模式。
    """

    def __init__(self):
        from statsmodels.tsa.filters.hp_filter import hpfilter
        self.hpfilter = hpfilter

    def filter_expanding(
        self,
        values: list[float],
        lamb: float = 129600
    ) -> list[float]:
        """
        扩张窗口 HP 滤波

        Args:
            values: 原始值序列
            lamb: 平滑参数

        Returns:
            List[float]: 趋势序列
        """
        if len(values) < 4:
            return values.copy()

        trends = []

        for i in range(len(values)):
            window = values[:i+1]

            if len(window) < 4:
                trends.append(values[i])
            else:
                # 调用 statsmodels
                trend, cycle = self.hpfilter(window, lamb=lamb)
                trends.append(float(trend[-1]))

        return trends


class KalmanFilterAdapter:
    """
    Kalman 滤波适配器

    封装 shared.infrastructure.kalman_filter.LocalLinearTrendFilter
    """

    def __init__(self, params: KalmanFilterParams):
        from shared.infrastructure.kalman_filter import KalmanState as InfraKalmanState
        from shared.infrastructure.kalman_filter import LocalLinearTrendFilter

        self.filter = LocalLinearTrendFilter(
            level_variance=params.level_variance,
            slope_variance=params.slope_variance,
            observation_variance=params.observation_variance,
        )
        self.InfraKalmanState = InfraKalmanState

    def filter_series(
        self,
        values: list[float],
        initial_state: KalmanFilterState | None = None
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

