"""Unit contracts for the Macro-owned trend filter projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from apps.data_center.application.dtos import (
    MacroDataPoint,
    MacroSeriesRequest,
    MacroSeriesResponse,
)
from apps.macro.application.trend_filter_service import MacroTrendFilterService
from shared.domain.interfaces import TrendResult
from shared.infrastructure.calculators import PandasTrendCalculator
from shared.infrastructure.kalman_filter import LocalLinearTrendFilter


class FakeMacroSeriesQuery:
    """Return a deliberately reverse-ordered governed macro series."""

    def __init__(self) -> None:
        self.requests: list[MacroSeriesRequest] = []

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        """Capture the request and return three display-ready observations."""

        self.requests.append(request)
        return MacroSeriesResponse(
            indicator_code=request.indicator_code,
            name_cn="制造业 PMI",
            period_type="M",
            data=[
                _point(date(2026, 3, 1), 53.0),
                _point(date(2026, 2, 1), 51.0),
                _point(date(2026, 1, 1), 50.0),
            ],
            total=3,
            data_source="data_center_fact",
            freshness_status="fresh",
            decision_grade="decision_safe",
            must_not_use_for_decision=False,
            latest_reporting_period=date(2026, 3, 1),
            latest_quality="verified",
        )


class FakeExpandingHpCalculator:
    """Expose whether the PIT-safe expanding HP method was selected."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[float], float, int]] = []

    def calculate_expanding_hp_trend(
        self,
        series: list[float],
        lamb: float = 129600,
        min_length: int = 12,
    ) -> TrendResult:
        """Return a deterministic trend without invoking statsmodels."""

        self.calls.append((series, lamb, min_length))
        return TrendResult(values=(49.0, 50.5, 52.0), z_scores=(0.0, 0.0, 0.0))


@dataclass
class FakeKalmanResult:
    """Structural result expected by the Kalman protocol."""

    filtered_levels: list[float]
    filtered_slopes: list[float]


class FakeKalmanCalculator:
    """Return deterministic one-way Kalman levels and slopes."""

    def __init__(self) -> None:
        self.calls: list[list[float]] = []

    def filter(
        self,
        observations: list[float],
        initial_level: float | None = None,
        initial_slope: float = 0.0,
    ) -> FakeKalmanResult:
        """Capture chronological observations and return a test projection."""

        self.calls.append(observations)
        return FakeKalmanResult(
            filtered_levels=[49.5, 50.75, 52.25],
            filtered_slopes=[0.0, 1.25, 1.5],
        )


def _point(period: date, value: float) -> MacroDataPoint:
    """Build one governed user-facing test observation."""

    return MacroDataPoint(
        indicator_code="CN_PMI",
        reporting_period=period,
        value=value,
        unit="指数",
        display_value=value,
        display_unit="指数",
        original_unit="指数",
        source="akshare",
        quality="verified",
        published_at=period,
        age_days=0,
        is_stale=False,
        freshness_status="fresh",
        decision_grade="decision_safe",
    )


def _service() -> tuple[
    MacroTrendFilterService,
    FakeMacroSeriesQuery,
    FakeExpandingHpCalculator,
    FakeKalmanCalculator,
]:
    """Build the use case with deterministic protocol fakes."""

    query = FakeMacroSeriesQuery()
    hp = FakeExpandingHpCalculator()
    kalman = FakeKalmanCalculator()
    return (
        MacroTrendFilterService(
            series_query=query,
            hp_calculator=hp,
            kalman_calculator=kalman,
        ),
        query,
        hp,
        kalman,
    )


def test_hp_filter_uses_chronological_expanding_window_only() -> None:
    """HP output must use the PIT-safe expanding method and portable rows."""

    service, query, hp, kalman = _service()

    result = service.execute(indicator_code="CN_PMI", filter_type="HP", limit=120)

    assert query.requests == [MacroSeriesRequest(indicator_code="CN_PMI", limit=120)]
    assert hp.calls == [([50.0, 51.0, 53.0], 129600, 12)]
    assert kalman.calls == []
    assert result.indicator_name == "制造业 PMI"
    assert result.unit == "指数"
    assert result.start_period == "2026-01-01"
    assert result.end_period == "2026-03-01"
    assert [row.period for row in result.rows] == [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert result.rows[0].cycle == pytest.approx(1.0)
    assert result.rows[0].slope is None
    assert result.must_not_use_for_decision is False


def test_kalman_filter_exposes_one_way_slope_without_persistence() -> None:
    """Kalman output should preserve the one-way levels and slopes."""

    service, _query, hp, kalman = _service()

    result = service.execute(
        indicator_code="CN_PMI",
        filter_type="KALMAN",
        limit=60,
    )

    assert hp.calls == []
    assert kalman.calls == [[50.0, 51.0, 53.0]]
    assert [row.trend for row in result.rows] == [49.5, 50.75, 52.25]
    assert [row.slope for row in result.rows] == [0.0, 1.25, 1.5]
    assert result.rows[-1].cycle == pytest.approx(0.75)


def test_shared_trend_algorithms_are_prefix_invariant() -> None:
    """Both production algorithms must leave an earlier PIT result unchanged."""

    observations = [
        50.0,
        50.4,
        50.1,
        50.8,
        51.2,
        51.0,
        51.7,
        52.0,
        51.8,
        52.4,
        52.9,
        52.7,
        53.3,
        53.8,
        54.1,
    ]
    hp = PandasTrendCalculator()
    hp_full = hp.calculate_expanding_hp_trend(observations)
    hp_prefix = hp.calculate_expanding_hp_trend(observations[:13])
    assert hp_full.values[12] == pytest.approx(hp_prefix.values[-1])

    kalman = LocalLinearTrendFilter()
    kalman_full = kalman.filter(observations)
    kalman_prefix = kalman.filter(observations[:13])
    assert kalman_full.filtered_levels[12] == pytest.approx(kalman_prefix.filtered_levels[-1])
    assert kalman_full.filtered_slopes[12] == pytest.approx(kalman_prefix.filtered_slopes[-1])


@pytest.mark.parametrize(
    ("indicator_code", "filter_type", "limit"),
    [
        ("", "HP", 120),
        ("CN_PMI", "UNKNOWN", 120),
        ("CN_PMI", "HP", 11),
        ("CN_PMI", "HP", 501),
    ],
)
def test_trend_filter_rejects_invalid_application_inputs(
    indicator_code: str,
    filter_type: str,
    limit: int,
) -> None:
    """The Application boundary must enforce the same bounded contract."""

    service, _query, _hp, _kalman = _service()

    with pytest.raises(ValueError):
        service.execute(
            indicator_code=indicator_code,
            filter_type=filter_type,
            limit=limit,
        )
