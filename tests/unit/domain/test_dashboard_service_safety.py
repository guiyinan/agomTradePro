"""Safety coverage for dynamic Dashboard Domain service inputs."""

from datetime import datetime

import pytest

from apps.dashboard.domain.entities import (
    AlertConfig,
    ChartConfig,
    WidgetType,
)
from apps.dashboard.domain.services import (
    DashboardAlertService,
    DashboardChartService,
    DashboardMetricService,
)


def test_metric_trend_ignores_non_numeric_previous_value() -> None:
    result = DashboardMetricService().calculate_metric(
        "score",
        {"score": 80.0},
        previous_data={"score": "70"},
    )

    assert result.value == 80.0
    assert result.trend is None
    assert result.trend_value is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_metric_rejects_non_finite_display_values(value: float) -> None:
    result = DashboardMetricService().calculate_metric("score", {"score": value})

    assert result.value is None
    assert result.formatted_value == "None"


def test_line_chart_skips_invalid_series_and_non_finite_points() -> None:
    config = ChartConfig(
        chart_type=WidgetType.LINE_CHART,
        x_axis_label="date",
        series=[
            {"name": "price", "y_key": "close"},
            {"name": ["invalid"], "y_key": "close"},
        ],
    )

    result = DashboardChartService().prepare_chart_data(
        config,
        [
            {"date": "2026-07-27", "close": 10.0},
            {"date": "2026-07-28", "close": float("nan")},
        ],
    )

    assert result["x"] == ["2026-07-27"]
    assert result["series"] == {"price": [10.0]}


def test_bar_chart_does_not_fabricate_zero_for_missing_or_invalid_values() -> None:
    config = ChartConfig(
        chart_type=WidgetType.BAR_CHART,
        x_axis_label="sector",
        y_axis_label="weight",
    )

    result = DashboardChartService().prepare_chart_data(
        config,
        [
            {"sector": "Tech", "weight": 30},
            {"sector": "Missing"},
            {"sector": "Broken", "weight": float("inf")},
        ],
    )

    assert result["categories"] == ["Tech"]
    assert result["values"] == [30.0]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_alerts_reject_boolean_and_non_finite_values(value: object) -> None:
    config = AlertConfig(
        alert_id="risk",
        name="Risk alert",
        metric="risk",
        threshold=1.0,
    )

    assert DashboardAlertService().evaluate_alerts([config], {"risk": value}) == []


def test_empty_cooldown_state_is_updated_on_trigger() -> None:
    config = AlertConfig(
        alert_id="risk",
        name="Risk alert",
        metric="risk",
        threshold=1.0,
    )
    cooldown_state: dict[str, datetime] = {}

    alerts = DashboardAlertService().evaluate_alerts(
        [config],
        {"risk": 2.0},
        cooldown_state,
    )

    assert len(alerts) == 1
    assert "risk" in cooldown_state


def test_naive_cooldown_timestamp_fails_closed() -> None:
    config = AlertConfig(
        alert_id="risk",
        name="Risk alert",
        metric="risk",
        threshold=1.0,
    )

    alerts = DashboardAlertService().evaluate_alerts(
        [config],
        {"risk": 2.0},
        {"risk": datetime(2026, 7, 28)},
    )

    assert alerts == []
