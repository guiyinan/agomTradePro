"""Serializer-only nullability and coverage-state contracts."""

from __future__ import annotations

from typing import Any

from apps.simulated_trading.interface.performance_serializers import (
    PerformanceRatiosSerializer,
    PerformanceReportResponseSerializer,
    PerformanceReturnsSerializer,
    PerformanceRiskSerializer,
    ValuationTimelinePointSerializer,
    ValuationTimelineResponseSerializer,
)


def test_performance_serializers_accept_null_metrics_and_required_unknown_coverage() -> None:
    """The output schema can express blocked metrics without dropping coverage state."""

    assert PerformanceReturnsSerializer().fields["twr"].allow_null is True
    assert PerformanceRiskSerializer().fields["max_drawdown"].allow_null is True
    assert PerformanceRatiosSerializer().fields["sharpe"].allow_null is True
    timeline_fields = ValuationTimelinePointSerializer().fields
    assert timeline_fields["net_value"].allow_null is True
    assert timeline_fields["twr_cumulative"].allow_null is True
    assert timeline_fields["drawdown"].allow_null is True
    assert timeline_fields["correction_coverage_known"].required is True
    assert timeline_fields["correction_coverage_known"].allow_null is False

    report_data: dict[str, Any] = {
        "period": {"start_date": "2026-10-01", "end_date": "2026-10-02", "days": 1},
        "returns": {"twr": None, "mwr": None, "annualized_twr": None, "annualized_mwr": None},
        "risk": {"volatility": None, "downside_volatility": None, "max_drawdown": None},
        "ratios": {"sharpe": None, "sortino": None, "calmar": None, "treynor": None},
        "benchmark": None,
        "trade_stats": {"win_rate": None, "profit_factor": None, "total_closed_trades": 0},
        "coverage": {"data_start": None, "data_end": None, "warnings": []},
        "warnings": ["FEE_CORRECTION_COVERAGE_UNKNOWN"],
    }
    report_serializer = PerformanceReportResponseSerializer(data=report_data)
    assert report_serializer.is_valid(), report_serializer.errors
    assert report_serializer.validated_data["returns"]["twr"] is None
    assert report_serializer.validated_data["benchmark"] is None

    timeline_serializer = ValuationTimelineResponseSerializer(
        data={
            "points": [
                {
                    "date": "2026-10-02",
                    "cash": 0,
                    "market_value": 0,
                    "total_value": 0,
                    "net_value": None,
                    "twr_cumulative": None,
                    "drawdown": None,
                    "correction_coverage_known": False,
                }
            ]
        }
    )
    assert timeline_serializer.is_valid(), timeline_serializer.errors
    assert timeline_serializer.validated_data["points"][0]["net_value"] is None
    assert timeline_serializer.validated_data["points"][0]["correction_coverage_known"] is False
