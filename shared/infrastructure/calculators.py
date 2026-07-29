"""
Pandas-based Trend Calculators.

Infrastructure layer implementation using Pandas for performance.
"""

from math import isfinite

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from statsmodels.tsa.filters.hp_filter import hpfilter  # type: ignore[import-untyped]

from ..domain.interfaces import TrendCalculatorProtocol, TrendResult


class PandasTrendCalculator(TrendCalculatorProtocol):
    """Pandas 实现的趋势计算器"""

    @staticmethod
    def _validated_series(series: list[float], *, minimum: int = 0) -> list[float]:
        """Return a detached finite numeric series."""

        if len(series) < minimum:
            raise ValueError(f"series must contain at least {minimum} observations")
        if len(series) > 1_000_000:
            raise ValueError("series exceeds the 1000000 observation limit")
        values: list[float] = []
        for value in series:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("series values must be numeric")
            normalized = float(value)
            if not isfinite(normalized):
                raise ValueError("series values must be finite")
            values.append(normalized)
        return values

    @staticmethod
    def _validated_lambda(lamb: float) -> float:
        """Return one positive finite HP smoothing parameter."""

        if isinstance(lamb, bool) or not isinstance(lamb, int | float):
            raise ValueError("lamb must be numeric")
        normalized = float(lamb)
        if not isfinite(normalized) or normalized <= 0:
            raise ValueError("lamb must be positive and finite")
        return normalized

    def calculate_hp_trend(self, series: list[float], lamb: float = 129600) -> TrendResult:
        """
        HP 滤波计算趋势（全量数据）

        注意：回测模式必须使用 calculate_expanding_hp_trend 避免后视偏差
        """
        values = self._validated_series(series, minimum=4)
        smoothing = self._validated_lambda(lamb)
        arr = np.asarray(values, dtype=float)
        _, trend = hpfilter(arr, lamb=smoothing)

        # 计算趋势的 Z-score
        trend_array = np.asarray(trend, dtype=float)
        std_trend = float(trend_array.std())
        if std_trend > 0 and isfinite(std_trend):
            z_scores = (trend_array - float(trend_array.mean())) / std_trend
        else:
            z_scores = np.zeros_like(trend_array)

        return TrendResult(
            values=tuple(float(value) for value in trend_array.tolist()),
            z_scores=tuple(float(value) for value in z_scores.tolist()),
        )

    def calculate_expanding_hp_trend(
        self,
        series: list[float],
        lamb: float = 129600,
        min_length: int = 12,
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
        values = self._validated_series(series)
        smoothing = self._validated_lambda(lamb)
        if (
            isinstance(min_length, bool)
            or not isinstance(min_length, int)
            or not 1 <= min_length <= 100_000
        ):
            raise ValueError("min_length must be an integer between 1 and 100000")
        n = len(values)
        trend_values: list[float] = []
        effective_min_length = max(min_length, 6)

        for t in range(n):
            if t < effective_min_length:
                # 数据不足时返回原始值
                trend_values.append(values[t])
            else:
                # 只用 [0, t] 的数据进行滤波
                truncated = values[: t + 1]
                arr = np.asarray(truncated, dtype=float)
                _, trend = hpfilter(arr, lamb=smoothing)
                trend_values.append(float(trend[-1]))

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
            z_scores=tuple(float(value) for value in z_scores.tolist()),
        )

    def calculate_z_scores(self, series: list[float], window: int = 60) -> tuple[float, ...]:
        """计算滚动 Z-score"""
        values = self._validated_series(series)
        if isinstance(window, bool) or not isinstance(window, int) or not 2 <= window <= 100_000:
            raise ValueError("window must be an integer between 2 and 100000")
        if not values:
            return ()
        s = pd.Series(values, dtype="float64")
        rolling_mean = s.rolling(window=window, min_periods=min(24, window)).mean()
        rolling_std = s.rolling(window=window, min_periods=min(24, window)).std()
        z = (s - rolling_mean) / rolling_std
        cleaned = z.replace([np.inf, -np.inf], 0).fillna(0)
        return tuple(float(value) for value in cleaned.tolist())
