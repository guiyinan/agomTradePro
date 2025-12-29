"""
Kalman Filter Implementation for Trend Extraction.

Infrastructure layer using NumPy for performance.
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class KalmanFilterResult:
    """Kalman 滤波结果"""
    filtered_levels: List[float]
    filtered_slopes: List[float]
    final_state: "KalmanState"


@dataclass
class KalmanState:
    """Kalman 滤波器状态（可持久化）"""
    level: float
    slope: float
    level_variance: float
    slope_variance: float
    level_slope_cov: float

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "slope": self.slope,
            "level_variance": self.level_variance,
            "slope_variance": self.slope_variance,
            "level_slope_cov": self.level_slope_cov,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KalmanState":
        return cls(**d)


class LocalLinearTrendFilter:
    """
    局部线性趋势 Kalman 滤波器

    特点：
    1. 单向滤波，无后视偏差
    2. 支持增量更新
    3. 可持久化状态
    """

    def __init__(self, level_variance: float = 0.01, slope_variance: float = 0.001, observation_variance: float = 1.0):
        self.level_variance = level_variance
        self.slope_variance = slope_variance
        self.observation_variance = observation_variance

        # 状态转移矩阵 F
        self.F = np.array([
            [1.0, 1.0],
            [0.0, 1.0]
        ])

        # 观测矩阵 H
        self.H = np.array([[1.0, 0.0]])

        # 过程噪声协方差 Q
        self.Q = np.array([
            [level_variance, 0.0],
            [0.0, slope_variance]
        ])

        # 观测噪声协方差 R
        self.R = np.array([[observation_variance]])

    def filter(
        self,
        observations: List[float],
        initial_level: Optional[float] = None,
        initial_slope: float = 0.0
    ) -> KalmanFilterResult:
        """对完整序列进行滤波"""
        n = len(observations)
        if n == 0:
            raise ValueError("Empty observations")

        # 初始化状态
        x = np.array([
            initial_level if initial_level is not None else observations[0],
            initial_slope
        ])
        P = np.array([
            [10.0, 0.0],
            [0.0, 1.0]
        ])

        filtered_levels = []
        filtered_slopes = []

        for y in observations:
            # 预测步骤
            x_pred = self.F @ x
            P_pred = self.F @ P @ self.F.T + self.Q

            # 更新步骤
            S = self.H @ P_pred @ self.H.T + self.R
            K = P_pred @ self.H.T @ np.linalg.inv(S)

            innovation = y - (self.H @ x_pred)[0]
            x = x_pred + (K @ np.array([[innovation]])).flatten()
            P = (np.eye(2) - K @ self.H) @ P_pred

            filtered_levels.append(x[0])
            filtered_slopes.append(x[1])

        final_state = KalmanState(
            level=x[0],
            slope=x[1],
            level_variance=P[0, 0],
            slope_variance=P[1, 1],
            level_slope_cov=P[0, 1]
        )

        return KalmanFilterResult(
            filtered_levels=filtered_levels,
            filtered_slopes=filtered_slopes,
            final_state=final_state
        )
