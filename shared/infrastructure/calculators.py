"""
Pandas-based Trend Calculators.

Infrastructure layer implementation using Pandas for performance.
"""

import pandas as pd
import numpy as np
from statsmodels.tsa.filters.hp_filter import hpfilter

from ..domain.interfaces import TrendCalculatorProtocol, TrendResult


class PandasTrendCalculator(TrendCalculatorProtocol):
    """Pandas 实现的趋势计算器"""

    def calculate_hp_trend(
        self,
        series: list[float],
        lamb: float = 129600
    ) -> TrendResult:
        """
        HP 滤波计算趋势（全量数据）

        注意：回测模式必须使用 calculate_expanding_hp_trend 避免后视偏差
        """
        arr = np.array(series)
        trend, cycle = hpfilter(arr, lamb=lamb)

        # 计算趋势的 Z-score
        z_scores = (trend - trend.mean()) / trend.std()

        return TrendResult(
            values=tuple(trend.tolist()),
            z_scores=tuple(z_scores.tolist())
        )

    def calculate_expanding_hp_trend(
        self,
        series: list[float],
        lamb: float = 129600,
        min_length: int = 12
    ) -> TrendResult:
        """
        扩张窗口 HP 滤波（避免后视偏差）

        对于每个时刻 t，只用 [0, t] 的数据进行滤波，
        模拟回测时的真实信息状态。

        Args:
            series: 时间序列数据
            lamb: HP 滤波平滑参数（月度数据推荐 129600）
            min_length: 最小数据长度，少于此时返回原始值

        Returns:
            TrendResult: 趋势值和 Z-score
        """
        n = len(series)
        trend_values = []
        min_length = max(min_length, 6)  # 至少需要 6 个数据点

        for t in range(n):
            if t < min_length:
                # 数据不足时返回原始值
                trend_values.append(series[t])
            else:
                # 只用 [0, t] 的数据进行滤波
                truncated = series[:t+1]
                arr = np.array(truncated)
                trend, _ = hpfilter(arr, lamb=lamb)
                trend_values.append(trend[-1])

        # 计算 Z-score
        arr_trend = np.array(trend_values)
        mean_trend = arr_trend.mean()
        std_trend = arr_trend.std()

        if std_trend > 0:
            z_scores = (arr_trend - mean_trend) / std_trend
        else:
            z_scores = np.zeros_like(arr_trend)

        return TrendResult(
            values=tuple(trend_values),
            z_scores=tuple(z_scores.tolist())
        )

    def calculate_z_scores(
        self,
        series: list[float],
        window: int = 60
    ) -> tuple[float, ...]:
        """计算滚动 Z-score"""
        s = pd.Series(series)
        rolling_mean = s.rolling(window=window, min_periods=24).mean()
        rolling_std = s.rolling(window=window, min_periods=24).std()
        z = (s - rolling_mean) / rolling_std
        return tuple(z.fillna(0).tolist())
