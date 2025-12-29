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
        HP 滤波计算趋势

        注意：回测模式必须使用扩张窗口避免后视偏差
        """
        arr = np.array(series)
        trend, cycle = hpfilter(arr, lamb=lamb)

        # 计算趋势的 Z-score
        z_scores = (trend - trend.mean()) / trend.std()

        return TrendResult(
            values=tuple(trend.tolist()),
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
