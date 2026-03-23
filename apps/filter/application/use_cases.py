"""
Use Cases for Filter Operations.

Application layer orchestrating filter workflows.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from ..domain.entities import (
    FilterResult,
    FilterSeries,
    FilterType,
    HPFilterParams,
    KalmanFilterParams,
    KalmanFilterState,
)
from ..infrastructure.repositories import (
    DjangoFilterRepository,
    HPFilterAdapter,
    KalmanFilterAdapter,
)


@dataclass
class ApplyFilterRequest:
    """应用滤波器的请求 DTO"""
    indicator_code: str  # 指标代码 (e.g., "PMI", "CPI")
    filter_type: FilterType  # 滤波器类型
    start_date: date | None = None  # 开始日期
    end_date: date | None = None  # 结束日期
    limit: int = 200  # 最大数据点数
    save_results: bool = True  # 是否保存结果


@dataclass
class ApplyFilterResponse:
    """应用滤波器的响应 DTO"""
    success: bool
    series: FilterSeries | None = None
    error: str | None = None
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


@dataclass
class GetFilterDataRequest:
    """获取滤波数据的请求"""
    indicator_code: str
    filter_type: FilterType
    start_date: date | None = None
    end_date: date | None = None


@dataclass
class GetFilterDataResponse:
    """获取滤波数据的响应"""
    success: bool
    results: list[FilterResult] = None
    error: str | None = None
    # 可序列化的数据
    dates: list[str] = None
    original_values: list[float] = None
    filtered_values: list[float] = None
    slopes: list[float | None] = None


@dataclass
class CompareFiltersRequest:
    """对比滤波器的请求"""
    indicator_code: str
    start_date: date | None = None
    end_date: date | None = None
    limit: int = 200


@dataclass
class CompareFiltersResponse:
    """对比滤波器的响应"""
    success: bool
    hp_results: dict | None = None
    kalman_results: dict | None = None
    error: str | None = None


class ApplyFilterUseCase:
    """
    应用滤波器的用例

    职责：
    1. 从 Repository 获取宏观数据
    2. 调用滤波器适配器计算
    3. 保存结果（可选）
    """

    def __init__(self, repository: DjangoFilterRepository):
        """
        Args:
            repository: DjangoFilterRepository 实例
        """
        self.repository = repository

    def execute(self, request: ApplyFilterRequest) -> ApplyFilterResponse:
        """
        执行滤波计算

        Args:
            request: 滤波请求

        Returns:
            ApplyFilterResponse: 滤波结果
        """
        try:
            # 1. 获取配置
            config = self.repository.get_filter_config(request.indicator_code)

            # 2. 获取原始数据
            data = self.repository.get_macro_indicator_data(
                indicator_code=request.indicator_code,
                start_date=request.start_date,
                end_date=request.end_date,
                limit=request.limit
            )

            if not data:
                return ApplyFilterResponse(
                    success=False,
                    error=f"无数据: {request.indicator_code}"
                )

            dates = [d['date'] for d in data]
            values = [d['value'] for d in data]

            # 3. 根据滤波器类型执行滤波
            if request.filter_type == FilterType.HP:
                series = self._apply_hp_filter(
                    request.indicator_code,
                    dates,
                    values,
                    config
                )
            elif request.filter_type == FilterType.KALMAN:
                series = self._apply_kalman_filter(
                    request.indicator_code,
                    dates,
                    values,
                    config
                )
            else:
                return ApplyFilterResponse(
                    success=False,
                    error=f"不支持的滤波器类型: {request.filter_type}"
                )

            # 4. 保存结果
            if request.save_results:
                self.repository.save_filter_results(series)

            return ApplyFilterResponse(
                success=True,
                series=series,
                warnings=[]
            )

        except Exception as e:
            return ApplyFilterResponse(
                success=False,
                error=str(e)
            )

    def _apply_hp_filter(
        self,
        indicator_code: str,
        dates: list[date],
        values: list[float],
        config: dict
    ) -> FilterSeries:
        """应用 HP 滤波"""
        adapter = HPFilterAdapter()
        lamb = config.get('hp_lambda', 129600.0)

        filtered_values = adapter.filter_expanding(values, lamb)

        results = [
            FilterResult(
                date=dates[i],
                original_value=values[i],
                filtered_value=filtered_values[i],
                trend=filtered_values[i],
                slope=None,
            )
            for i in range(len(dates))
        ]

        return FilterSeries(
            indicator_code=indicator_code,
            filter_type=FilterType.HP,
            params={'lamb': lamb},
            results=results,
            calculated_at=date.today()
        )

    def _apply_kalman_filter(
        self,
        indicator_code: str,
        dates: list[date],
        values: list[float],
        config: dict
    ) -> FilterSeries:
        """应用 Kalman 滤波"""
        # 获取保存的状态（用于增量更新）
        saved_state = self.repository.get_latest_kalman_state(indicator_code)

        params = KalmanFilterParams(
            level_variance=config.get('kalman_level_variance', 0.05),
            slope_variance=config.get('kalman_slope_variance', 0.005),
            observation_variance=config.get('kalman_observation_variance', 0.5),
        )

        adapter = KalmanFilterAdapter(params)
        levels, slopes, final_state = adapter.filter_series(values, saved_state)

        results = [
            FilterResult(
                date=dates[i],
                original_value=values[i],
                filtered_value=levels[i],
                trend=levels[i],
                slope=slopes[i],
            )
            for i in range(len(dates))
        ]

        # 保存最终状态
        self.repository.save_kalman_state(
            indicator_code,
            final_state,
            {
                'level_variance': params.level_variance,
                'slope_variance': params.slope_variance,
                'observation_variance': params.observation_variance,
            }
        )

        return FilterSeries(
            indicator_code=indicator_code,
            filter_type=FilterType.KALMAN,
            params={
                'level_variance': params.level_variance,
                'slope_variance': params.slope_variance,
                'observation_variance': params.observation_variance,
            },
            results=results,
            calculated_at=date.today()
        )


class GetFilterDataUseCase:
    """获取滤波数据的用例"""

    def __init__(self, repository: DjangoFilterRepository):
        self.repository = repository

    def execute(self, request: GetFilterDataRequest) -> GetFilterDataResponse:
        """
        获取已保存的滤波结果

        Args:
            request: 数据请求

        Returns:
            GetFilterDataResponse: 滤波数据
        """
        try:
            results = self.repository.get_filter_results(
                indicator_code=request.indicator_code,
                filter_type=request.filter_type,
                start_date=request.start_date,
                end_date=request.end_date
            )

            if not results:
                return GetFilterDataResponse(
                    success=False,
                    error=f"无滤波结果: {request.indicator_code} ({request.filter_type.value})"
                )

            return GetFilterDataResponse(
                success=True,
                results=results,
                dates=[r.date.isoformat() for r in results],
                original_values=[r.original_value for r in results],
                filtered_values=[r.filtered_value for r in results],
                slopes=[r.slope for r in results],
            )

        except Exception as e:
            return GetFilterDataResponse(
                success=False,
                error=str(e)
            )


class CompareFiltersUseCase:
    """对比滤波器的用例"""

    def __init__(self, apply_use_case: ApplyFilterUseCase):
        self.apply_use_case = apply_use_case

    def execute(self, request: CompareFiltersRequest) -> CompareFiltersResponse:
        """
        对比 HP 和 Kalman 滤波

        Args:
            request: 对比请求

        Returns:
            CompareFiltersResponse: 对比结果
        """
        try:
            # 应用 HP 滤波
            hp_response = self.apply_use_case.execute(ApplyFilterRequest(
                indicator_code=request.indicator_code,
                filter_type=FilterType.HP,
                start_date=request.start_date,
                end_date=request.end_date,
                limit=request.limit,
                save_results=False,  # 不保存对比结果
            ))

            # 应用 Kalman 滤波
            kalman_response = self.apply_use_case.execute(ApplyFilterRequest(
                indicator_code=request.indicator_code,
                filter_type=FilterType.KALMAN,
                start_date=request.start_date,
                end_date=request.end_date,
                limit=request.limit,
                save_results=False,
            ))

            return CompareFiltersResponse(
                success=hp_response.success and kalman_response.success,
                hp_results=self._serialize_series(hp_response.series) if hp_response.success else None,
                kalman_results=self._serialize_series(kalman_response.series) if kalman_response.success else None,
                error=hp_response.error or kalman_response.error,
            )

        except Exception as e:
            return CompareFiltersResponse(
                success=False,
                error=str(e)
            )

    def _serialize_series(self, series: FilterSeries) -> dict:
        """序列化滤波序列为字典"""
        return {
            'indicator_code': series.indicator_code,
            'filter_type': series.filter_type.value,
            'params': series.params,
            'dates': [r.date.isoformat() for r in series.results],
            'original_values': [r.original_value for r in series.results],
            'filtered_values': [r.filtered_value for r in series.results],
            'slopes': [r.slope for r in series.results],
        }
