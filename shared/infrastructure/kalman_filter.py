"""
Kalman Filter Implementation for Trend Extraction.

Infrastructure layer using NumPy for performance.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import TypedDict

import numpy as np


class KalmanStatePayload(TypedDict):
    """Serialized Kalman state contract."""

    level: float
    slope: float
    level_variance: float
    slope_variance: float
    level_slope_cov: float


def _finite_float(value: object, *, field_name: str) -> float:
    """Return one finite numeric Kalman input."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True)
class KalmanFilterResult:
    """Kalman 滤波结果"""

    filtered_levels: list[float]
    filtered_slopes: list[float]
    final_state: "KalmanState"


@dataclass(frozen=True)
class KalmanState:
    """Kalman 滤波器状态（可持久化）"""

    level: float
    slope: float
    level_variance: float
    slope_variance: float
    level_slope_cov: float

    def __post_init__(self) -> None:
        """Reject non-finite or negative-variance persisted states."""

        for field_name in (
            "level",
            "slope",
            "level_variance",
            "slope_variance",
            "level_slope_cov",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite_float(getattr(self, field_name), field_name=field_name),
            )
        if self.level_variance < 0 or self.slope_variance < 0:
            raise ValueError("Kalman state variances cannot be negative")

    def to_dict(self) -> KalmanStatePayload:
        return {
            "level": self.level,
            "slope": self.slope,
            "level_variance": self.level_variance,
            "slope_variance": self.slope_variance,
            "level_slope_cov": self.level_slope_cov,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "KalmanState":
        """Build a state from an exact, finite mapping contract."""

        expected_fields = {
            "level",
            "slope",
            "level_variance",
            "slope_variance",
            "level_slope_cov",
        }
        if set(payload) != expected_fields:
            raise ValueError("Kalman state payload has invalid fields")
        return cls(
            level=_finite_float(payload["level"], field_name="level"),
            slope=_finite_float(payload["slope"], field_name="slope"),
            level_variance=_finite_float(payload["level_variance"], field_name="level_variance"),
            slope_variance=_finite_float(payload["slope_variance"], field_name="slope_variance"),
            level_slope_cov=_finite_float(payload["level_slope_cov"], field_name="level_slope_cov"),
        )


class LocalLinearTrendFilter:
    """
    局部线性趋势 Kalman 滤波器

    特点：
    1. 单向滤波，无后视偏差
    2. 支持增量更新
    3. 可持久化状态
    """

    def __init__(
        self,
        level_variance: float = 0.01,
        slope_variance: float = 0.001,
        observation_variance: float = 1.0,
    ) -> None:
        self.level_variance = _finite_float(level_variance, field_name="level_variance")
        self.slope_variance = _finite_float(slope_variance, field_name="slope_variance")
        self.observation_variance = _finite_float(
            observation_variance, field_name="observation_variance"
        )
        if self.level_variance < 0 or self.slope_variance < 0:
            raise ValueError("process variances cannot be negative")
        if self.observation_variance <= 0:
            raise ValueError("observation_variance must be positive")

        # 状态转移矩阵 F
        self.F = np.array([[1.0, 1.0], [0.0, 1.0]])

        # 观测矩阵 H
        self.H = np.array([[1.0, 0.0]])

        # 过程噪声协方差 Q
        self.Q = np.array([[level_variance, 0.0], [0.0, slope_variance]])

        # 观测噪声协方差 R
        self.R = np.array([[observation_variance]])

    def filter(
        self,
        observations: list[float],
        initial_level: float | None = None,
        initial_slope: float = 0.0,
    ) -> KalmanFilterResult:
        """对完整序列进行滤波"""
        if len(observations) > 1_000_000:
            raise ValueError("observations exceed the 1000000 item limit")
        normalized_observations = [
            _finite_float(value, field_name="observation") for value in observations
        ]
        n = len(normalized_observations)
        if n == 0:
            raise ValueError("Empty observations")
        normalized_initial_level = (
            _finite_float(initial_level, field_name="initial_level")
            if initial_level is not None
            else normalized_observations[0]
        )
        normalized_initial_slope = _finite_float(initial_slope, field_name="initial_slope")

        # 初始化状态
        x = np.array(
            [
                normalized_initial_level,
                normalized_initial_slope,
            ]
        )
        P = np.array([[10.0, 0.0], [0.0, 1.0]])

        filtered_levels: list[float] = []
        filtered_slopes: list[float] = []

        for y in normalized_observations:
            # 预测步骤
            x_pred = self.F @ x
            P_pred = self.F @ P @ self.F.T + self.Q

            # 更新步骤
            S = self.H @ P_pred @ self.H.T + self.R
            K = P_pred @ self.H.T @ np.linalg.inv(S)

            innovation = y - (self.H @ x_pred)[0]
            x = x_pred + (K @ np.array([[innovation]])).flatten()
            P = (np.eye(2) - K @ self.H) @ P_pred

            filtered_levels.append(float(x[0]))
            filtered_slopes.append(float(x[1]))

        final_state = KalmanState(
            level=float(x[0]),
            slope=float(x[1]),
            level_variance=max(float(P[0, 0]), 0.0),
            slope_variance=max(float(P[1, 1]), 0.0),
            level_slope_cov=float(P[0, 1]),
        )

        return KalmanFilterResult(
            filtered_levels=filtered_levels,
            filtered_slopes=filtered_slopes,
            final_state=final_state,
        )

    def update_single(self, new_observation: float, current_state: KalmanState) -> KalmanState:
        """
        增量更新单个新观测值

        用于实时场景，当获得新的数据点时更新滤波器状态，
        而不需要重新处理整个历史序列。

        Args:
            new_observation: 新的观测值
            current_state: 当前滤波器状态

        Returns:
            KalmanState: 更新后的状态
        """
        # 从状态恢复向量和协方差矩阵
        observation = _finite_float(new_observation, field_name="new_observation")
        x = np.array([current_state.level, current_state.slope])
        P = np.array(
            [
                [current_state.level_variance, current_state.level_slope_cov],
                [current_state.level_slope_cov, current_state.slope_variance],
            ]
        )

        # 预测步骤
        x_pred = self.F @ x
        P_pred = self.F @ P @ self.F.T + self.Q

        # 更新步骤
        S = self.H @ P_pred @ self.H.T + self.R
        K = P_pred @ self.H.T @ np.linalg.inv(S)

        innovation = observation - (self.H @ x_pred)[0]
        x_new = x_pred + (K @ np.array([[innovation]])).flatten()
        P_new = (np.eye(2) - K @ self.H) @ P_pred

        return KalmanState(
            level=float(x_new[0]),
            slope=float(x_new[1]),
            level_variance=max(float(P_new[0, 0]), 0.0),
            slope_variance=max(float(P_new[1, 1]), 0.0),
            level_slope_cov=float(P_new[0, 1]),
        )

    def predict_next(self, current_state: KalmanState, steps: int = 1) -> float:
        """
        基于当前状态预测未来值

        Args:
            current_state: 当前滤波器状态
            steps: 预测步数（默认 1 步）

        Returns:
            float: 预测值
        """
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 100_000:
            raise ValueError("steps must be an integer between 1 and 100000")
        x = np.array([current_state.level, current_state.slope])
        x_pred = x

        for _ in range(steps):
            x_pred = self.F @ x_pred

        return float(x_pred[0])
