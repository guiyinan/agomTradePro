"""Composition root for Macro application services."""

from __future__ import annotations

from apps.data_center.application.dtos import MacroSeriesRequest, MacroSeriesResponse
from apps.data_center.application.public import get_published_macro_series_response
from apps.macro.application.trend_filter_service import (
    MacroTrendFilterService,
)
from shared.infrastructure.calculators import PandasTrendCalculator
from shared.infrastructure.kalman_filter import LocalLinearTrendFilter


class _PublishedMacroSeriesQuery:
    """Resolve macro trend reads through the Data Center Public Port."""

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        """Return one publication-bound series or a fail-closed response."""

        return get_published_macro_series_response(
            request.indicator_code,
            publication_key=request.indicator_code,
            start=request.start,
            end=request.end,
            limit=request.limit,
            source=request.source,
        )


def build_macro_trend_filter_service() -> MacroTrendFilterService:
    """Compose the governed series query and one-way trend calculators."""

    return MacroTrendFilterService(
        series_query=_PublishedMacroSeriesQuery(),
        hp_calculator=PandasTrendCalculator(),
        kalman_calculator=LocalLinearTrendFilter(),
    )


__all__ = ["build_macro_trend_filter_service"]
