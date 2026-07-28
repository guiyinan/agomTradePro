"""Read-only macro trend filtering owned by the Macro application layer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from apps.data_center.application.dtos import (
    MacroSeriesRequest,
    MacroSeriesResponse,
)
from shared.domain.interfaces import TrendResult

INDICATOR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
SUPPORTED_TREND_FILTER_TYPES = frozenset({"HP", "KALMAN"})
MIN_TREND_FILTER_LIMIT = 12
MAX_TREND_FILTER_LIMIT = 500


class MacroSeriesQueryProtocol(Protocol):
    """Application contract for governed macro-series reads."""

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        """Return one governed macro series."""


class ExpandingHpCalculatorProtocol(Protocol):
    """PIT-safe HP trend calculator contract."""

    def calculate_expanding_hp_trend(
        self,
        series: list[float],
        lamb: float = 129600,
        min_length: int = 12,
    ) -> TrendResult:
        """Return expanding-window HP levels without look-ahead."""


class KalmanResultProtocol(Protocol):
    """Structural result returned by a one-way Kalman calculator."""

    filtered_levels: list[float]
    filtered_slopes: list[float]


class OneWayKalmanCalculatorProtocol(Protocol):
    """One-way local-linear trend calculator contract."""

    def filter(
        self,
        observations: list[float],
        initial_level: float | None = None,
        initial_slope: float = 0.0,
    ) -> KalmanResultProtocol:
        """Return filtered levels and slopes without future observations."""


@dataclass(frozen=True)
class MacroTrendFilterRow:
    """One portable trend-filter chart row."""

    period: str
    original: float
    trend: float
    cycle: float
    slope: float | None


@dataclass(frozen=True)
class MacroTrendFilterResult:
    """Governed metadata and portable rows for one trend-filter read."""

    indicator_code: str
    indicator_name: str
    filter_type: str
    unit: str
    data_source: str
    freshness_status: str
    decision_grade: str
    must_not_use_for_decision: bool
    blocked_reason: str
    latest_quality: str
    start_period: str
    end_period: str
    rows: tuple[MacroTrendFilterRow, ...]


class MacroTrendFilterService:
    """Project governed macro facts through PIT-safe trend algorithms."""

    def __init__(
        self,
        *,
        series_query: MacroSeriesQueryProtocol,
        hp_calculator: ExpandingHpCalculatorProtocol,
        kalman_calculator: OneWayKalmanCalculatorProtocol,
    ) -> None:
        self._series_query = series_query
        self._hp_calculator = hp_calculator
        self._kalman_calculator = kalman_calculator

    def execute(
        self,
        *,
        indicator_code: str,
        filter_type: str,
        limit: int,
    ) -> MacroTrendFilterResult:
        """Return chronological original, trend, cycle, and slope rows."""

        normalized_code = indicator_code.strip()
        normalized_filter_type = filter_type.strip().upper()
        self._validate_input(
            indicator_code=normalized_code,
            filter_type=normalized_filter_type,
            limit=limit,
        )
        response = self._series_query.execute(
            MacroSeriesRequest(
                indicator_code=normalized_code,
                limit=limit,
            )
        )
        points = sorted(response.data, key=lambda point: point.reporting_period)
        observations = [float(point.display_value) for point in points]
        trend_values, slopes = self._calculate_trend(
            observations=observations,
            filter_type=normalized_filter_type,
        )
        rows = tuple(
            MacroTrendFilterRow(
                period=point.reporting_period.isoformat(),
                original=original,
                trend=trend,
                cycle=original - trend,
                slope=slope,
            )
            for point, original, trend, slope in zip(
                points,
                observations,
                trend_values,
                slopes,
                strict=True,
            )
        )
        latest_point = points[-1] if points else None
        return MacroTrendFilterResult(
            indicator_code=response.indicator_code,
            indicator_name=response.name_cn,
            filter_type=normalized_filter_type,
            unit=(
                str(latest_point.display_unit or latest_point.unit)
                if latest_point is not None
                else ""
            ),
            data_source=response.data_source,
            freshness_status=response.freshness_status,
            decision_grade=response.decision_grade,
            must_not_use_for_decision=response.must_not_use_for_decision,
            blocked_reason=response.blocked_reason,
            latest_quality=response.latest_quality,
            start_period=rows[0].period if rows else "",
            end_period=rows[-1].period if rows else "",
            rows=rows,
        )

    @staticmethod
    def _validate_input(
        *,
        indicator_code: str,
        filter_type: str,
        limit: int,
    ) -> None:
        """Reject identifiers, algorithms, and windows outside the contract."""

        if INDICATOR_CODE_PATTERN.fullmatch(indicator_code) is None:
            raise ValueError("指标代码只能包含字母、数字、点、冒号、下划线或连字符")
        if filter_type not in SUPPORTED_TREND_FILTER_TYPES:
            raise ValueError("滤波器只支持 HP 或 KALMAN")
        if not MIN_TREND_FILTER_LIMIT <= limit <= MAX_TREND_FILTER_LIMIT:
            raise ValueError(
                f"历史点数必须在 {MIN_TREND_FILTER_LIMIT}-{MAX_TREND_FILTER_LIMIT} 之间"
            )

    def _calculate_trend(
        self,
        *,
        observations: list[float],
        filter_type: str,
    ) -> tuple[list[float], list[float | None]]:
        """Select the PIT-safe algorithm and normalize its numeric output."""

        if not observations:
            return [], []
        if filter_type == "HP":
            hp_result = self._hp_calculator.calculate_expanding_hp_trend(
                observations,
                129600,
                12,
            )
            trend = [float(value) for value in hp_result.values]
            slopes: list[float | None] = [None] * len(trend)
        else:
            kalman_result = self._kalman_calculator.filter(observations)
            trend = [float(value) for value in kalman_result.filtered_levels]
            slopes = [float(value) for value in kalman_result.filtered_slopes]
        if len(trend) != len(observations) or len(slopes) != len(observations):
            raise ValueError("趋势计算器返回的数据点数量与原序列不一致")
        return trend, slopes


__all__ = [
    "INDICATOR_CODE_PATTERN",
    "MAX_TREND_FILTER_LIMIT",
    "MIN_TREND_FILTER_LIMIT",
    "MacroTrendFilterResult",
    "MacroTrendFilterRow",
    "MacroTrendFilterService",
    "SUPPORTED_TREND_FILTER_TYPES",
]
