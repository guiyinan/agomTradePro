"""
Domain Services for Filter Operations.

Pure business logic using only Python standard library.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Protocol, Tuple

from .entities import FilterResult, FilterSeries, FilterType, HPFilterParams, KalmanFilterParams


class FilterProtocol(Protocol):
    """滤波器接口"""

    def filter_series(
        self,
        dates: list[date],
        values: list[float],
        params: dict | None = None
    ) -> FilterSeries:
        """对完整序列进行滤波"""
        ...


class HPFilterService:
    """
    HP 滤波服务（Domain 层纯算法）

    使用扩张窗口模式，避免后视偏差。
    """

    def __init__(self, params: HPFilterParams = None):
        """
        Args:
            params: HP 滤波参数
        """
        self.params = params or HPFilterParams.for_monthly_data()

    def filter_series(
        self,
        dates: list[date],
        values: list[float],
        params: HPFilterParams | None = None
    ) -> FilterSeries:
        """
        使用扩张窗口进行 HP 滤波

        每个时点只用历史数据计算趋势，避免后视偏差。

        Args:
            dates: 日期列表
            values: 原始值列表
            params: 滤波参数（可选）

        Returns:
            FilterSeries: 滤波结果
        """
        if len(dates) != len(values):
            raise ValueError("日期和值列表长度必须一致")

        if len(values) < 4:
            raise ValueError("HP 滤波至少需要 4 个数据点")

        params = params or self.params
        results = []

        for i in range(len(values)):
            # 使用扩张窗口：只使用 [0, i] 的数据
            window_values = values[:i+1]

            if len(window_values) < 4:
                # 数据不足，返回原始值
                trend = values[i]
            else:
                # 计算 HP 滤波趋势（取最后一个值）
                trend = self._get_expanding_hp_trend(window_values, params.lamb)

            results.append(FilterResult(
                date=dates[i],
                original_value=values[i],
                filtered_value=trend
            ))

        return FilterSeries(
            indicator_code="UNKNOWN",
            filter_type=FilterType.HP,
            params={"lamb": params.lamb},
            results=results,
            calculated_at=date.today()
        )

    def _get_expanding_hp_trend(self, series: list[float], lamb: float) -> float:
        """
        扩张窗口 HP 滤波

        Domain 层纯实现，使用简化算法。
        完整实现需要调用 Infrastructure 层的 Statsmodels 适配器。

        这里使用移动平均作为近似实现。
        """
        n = len(series)

        # 使用中心移动平均作为趋势近似
        # 扩张窗口意味着我们只能用前面的数据
        window_size = min(6, n)  # 6期移动平均

        if n < window_size:
            return sum(series) / len(series)

        # 取最后 window_size 期的平均
        recent = series[-window_size:]
        return sum(recent) / len(recent)


class KalmanFilterService:
    """
    Kalman 滤波服务（Domain 层）

    定义接口和业务逻辑，具体实现由 Infrastructure 层提供。
    """

    def __init__(self, params: KalmanFilterParams = None):
        """
        Args:
            params: Kalman 滤波参数
        """
        self.params = params or KalmanFilterParams.for_monthly_macro()

    def filter_series(
        self,
        dates: list[date],
        values: list[float],
        params: KalmanFilterParams | None = None,
        initial_state: dict | None = None
    ) -> FilterSeries:
        """
        Kalman 滤波

        注意：完整实现需要 Infrastructure 层的 NumPy 适配器。
        这里定义接口和业务逻辑。

        Args:
            dates: 日期列表
            values: 原始值列表
            params: 滤波参数（可选）
            initial_state: 初始状态（可选，用于增量更新）

        Returns:
            FilterSeries: 滤波结果
        """
        # 这个方法需要在 Infrastructure 层实现具体计算
        # 这里只是定义接口
        raise NotImplementedError(
            "Kalman 滤波需要 Infrastructure 层的实现。"
            "使用 shared.infrastructure.kalman_filter.LocalLinearTrendFilter"
        )


@dataclass(frozen=True)
class FilterComparison:
    """滤波器对比结果"""
    indicator_code: str
    hp_results: FilterSeries | None
    kalman_results: FilterSeries | None
    comparison_date: date


def compare_filters(
    dates: list[date],
    values: list[float],
    indicator_code: str = "UNKNOWN"
) -> FilterComparison:
    """
    对比 HP 和 Kalman 滤波结果

    Args:
        dates: 日期列表
        values: 原始值列表
        indicator_code: 指标代码

    Returns:
        FilterComparison: 对比结果
    """
    hp_service = HPFilterService()
    hp_results = hp_service.filter_series(dates, values)
    hp_results = FilterSeries(
        indicator_code=indicator_code,
        filter_type=hp_results.filter_type,
        params=hp_results.params,
        results=hp_results.results,
        calculated_at=hp_results.calculated_at
    )

    # Kalman 需要基础设施层实现
    return FilterComparison(
        indicator_code=indicator_code,
        hp_results=hp_results,
        kalman_results=None,
        comparison_date=date.today()
    )


def detect_turning_points(
    results: list[FilterResult],
    window: int = 3
) -> list[dict]:
    """
    检测趋势转折点

    Args:
        results: 滤波结果列表
        window: 检测窗口大小

    Returns:
        List[Dict]: 转折点列表
    """
    if len(results) < window * 2:
        return []

    turning_points = []
    slopes = []

    # 计算斜率
    for i in range(1, len(results)):
        slope = results[i].filtered_value - results[i-1].filtered_value
        slopes.append(slope)

    # 检测极值点
    for i in range(window, len(slopes) - window):
        before = slopes[i-window:i]
        after = slopes[i+1:i+1+window]

        # 检查符号变化
        before_avg = sum(before) / len(before)
        after_avg = sum(after) / len(after)

        if before_avg > 0 and after_avg < 0:
            turning_points.append({
                "date": results[i+1].date,
                "type": "peak",
                "value": results[i+1].filtered_value
            })
        elif before_avg < 0 and after_avg > 0:
            turning_points.append({
                "date": results[i+1].date,
                "type": "trough",
                "value": results[i+1].filtered_value
            })

    return turning_points
