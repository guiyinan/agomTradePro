"""Composition root for Macro application services."""

from __future__ import annotations

from apps.data_center.application.interface_services import (
    make_query_macro_series_use_case,
)
from apps.macro.application.trend_filter_service import MacroTrendFilterService
from shared.infrastructure.calculators import PandasTrendCalculator
from shared.infrastructure.kalman_filter import LocalLinearTrendFilter


def build_macro_trend_filter_service() -> MacroTrendFilterService:
    """Compose the governed series query and one-way trend calculators."""

    return MacroTrendFilterService(
        series_query=make_query_macro_series_use_case(),
        hp_calculator=PandasTrendCalculator(),
        kalman_calculator=LocalLinearTrendFilter(),
    )


__all__ = ["build_macro_trend_filter_service"]
