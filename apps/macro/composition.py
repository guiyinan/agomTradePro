"""Composition root for Macro application services."""

from __future__ import annotations

from dataclasses import replace

from apps.data_center.application.dtos import MacroSeriesRequest, MacroSeriesResponse
from apps.data_center.application.interface_services import (
    make_query_macro_series_use_case,
)
from apps.data_center.application.public import (
    get_current_publication_freshness_gate,
    get_publication_member_fact_pks,
)
from apps.macro.application.trend_filter_service import (
    MacroSeriesQueryProtocol,
    MacroTrendFilterService,
)
from shared.infrastructure.calculators import PandasTrendCalculator
from shared.infrastructure.kalman_filter import LocalLinearTrendFilter


class _PublishedMacroSeriesQuery:
    """Bind macro trend reads to the active publication member snapshot."""

    def __init__(self, delegate: MacroSeriesQueryProtocol) -> None:
        self._delegate = delegate

    def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
        """Return one publication-bound series or a fail-closed response."""

        gate = get_current_publication_freshness_gate("macro.fact", request.indicator_code)
        blocked_reason = str((gate or {}).get("blocked_reason") or "canonical_publication_missing")
        publication_id = (gate or {}).get("publication_id")
        if (
            gate is None
            or bool(gate.get("must_not_use_for_decision"))
            or not isinstance(publication_id, str)
            or not publication_id
        ):
            return MacroSeriesResponse(
                indicator_code=request.indicator_code,
                name_cn=request.indicator_code,
                period_type="",
                data_source="data_center_publication",
                freshness_status=str((gate or {}).get("freshness_status") or "missing"),
                decision_grade="blocked",
                must_not_use_for_decision=True,
                blocked_reason=blocked_reason,
            )

        member_pks = get_publication_member_fact_pks(
            publication_id,
            dataset_key="macro.fact",
            expected_fact_table="data_center_macro_fact",
        )
        if not member_pks:
            return MacroSeriesResponse(
                indicator_code=request.indicator_code,
                name_cn=request.indicator_code,
                period_type="",
                data_source="data_center_publication",
                freshness_status="missing",
                decision_grade="blocked",
                must_not_use_for_decision=True,
                blocked_reason="canonical_publication_members_missing",
            )

        return self._delegate.execute(replace(request, fact_pks=list(member_pks)))


def build_macro_trend_filter_service() -> MacroTrendFilterService:
    """Compose the governed series query and one-way trend calculators."""

    return MacroTrendFilterService(
        series_query=_PublishedMacroSeriesQuery(make_query_macro_series_use_case()),
        hp_calculator=PandasTrendCalculator(),
        kalman_calculator=LocalLinearTrendFilter(),
    )


__all__ = ["build_macro_trend_filter_service"]
