"""Context loading helpers for the advisor decision-sheet use case."""

from __future__ import annotations

from typing import Any

from apps.decision_rhythm.application.advisor_contracts import (
    AdvisorOrderIntent,
    AttributionContextProviderProtocol,
    DataHealthProviderProtocol,
    ExposureProviderProtocol,
    RecommendationPerformanceProviderProtocol,
    RecommendationTrackingProviderProtocol,
    RiskGateProviderProtocol,
)
from apps.decision_rhythm.application.advisor_execution import (
    _normalize_exposure_map,
)
from apps.decision_rhythm.application.advisor_intents import (
    _dedupe_preserve_order,
    _normalize_data_health_payload,
    _normalize_risk_policy_context,
    _recommendation_id,
    _unique_asset_codes,
)
from apps.decision_rhythm.application.advisor_performance import (
    _date_from_any,
    _performance_outcome_date,
    _recommendation_performance_payload,
    _recommendation_tracking_payload,
)


class AdvisorSheetContextMixin:
    """Load risk, health, exposure, tracking, and attribution context."""

    risk_gate_provider: RiskGateProviderProtocol
    data_health_provider: DataHealthProviderProtocol
    exposure_provider: ExposureProviderProtocol
    tracking_provider: RecommendationTrackingProviderProtocol
    performance_provider: RecommendationPerformanceProviderProtocol
    attribution_context_provider: AttributionContextProviderProtocol

    def _get_risk_policy_context(self, *, account_id: str) -> dict[str, Any]:
        try:
            return self.risk_gate_provider.get_policy_context(account_id=account_id)
        except Exception as exc:
            return _normalize_risk_policy_context(
                {
                    "account_id": account_id,
                    "warnings": [f"risk_policy_unavailable:{exc}"],
                },
                unavailable=True,
            )

    def _get_data_health(self, *, asset_codes: list[str]) -> dict[str, Any]:
        try:
            return _normalize_data_health_payload(
                self.data_health_provider.get_health(asset_codes=asset_codes)
            )
        except Exception as exc:
            return _normalize_data_health_payload(
                {
                    "status": "blocked",
                    "asset_codes": asset_codes,
                    "must_not_use_for_decision": True,
                    "blocked_reasons": [f"decision_data_health_unavailable:{exc}"],
                }
            )

    def _get_exposure_map(self, *, asset_codes: list[str]) -> dict[str, dict[str, Any]]:
        try:
            return _normalize_exposure_map(
                self.exposure_provider.get_asset_exposures(asset_codes=asset_codes)
            )
        except Exception as exc:
            return {
                asset_code: {"lookup_error": str(exc)}
                for asset_code in _unique_asset_codes(asset_codes)
            }

    def _get_recommendation_tracking(
        self,
        *,
        account_id: str,
        order_intents: list[AdvisorOrderIntent],
        recommendations: list[Any],
        user: Any,
    ) -> dict[str, dict[str, Any]]:
        recommendation_ids = _dedupe_preserve_order(
            [
                recommendation_id
                for intent in order_intents
                for recommendation_id in intent.source_recommendation_ids
            ]
        )
        recommendation_by_id = {
            _recommendation_id(recommendation): recommendation
            for recommendation in recommendations
            if _recommendation_id(recommendation)
        }
        try:
            links_by_id = self.tracking_provider.get_execution_links(
                account_id=account_id,
                recommendation_ids=recommendation_ids,
                user=user,
            )
        except Exception as exc:
            return {
                recommendation_id: self._recommendation_tracking_payload_with_context(
                    recommendation_id=recommendation_id,
                    recommendation=recommendation_by_id.get(recommendation_id),
                    execution_links=[],
                    lookup_error=str(exc),
                )
                for recommendation_id in recommendation_ids
            }
        return {
            recommendation_id: self._recommendation_tracking_payload_with_context(
                recommendation_id=recommendation_id,
                recommendation=recommendation_by_id.get(recommendation_id),
                execution_links=links_by_id.get(recommendation_id, []),
                lookup_error="",
            )
            for recommendation_id in recommendation_ids
        }

    def _recommendation_tracking_payload_with_context(
        self,
        *,
        recommendation_id: str,
        recommendation: Any | None,
        execution_links: list[dict[str, Any]],
        lookup_error: str,
    ) -> dict[str, Any]:
        performance = _recommendation_performance_payload(
            recommendation=recommendation,
            performance_provider=self.performance_provider,
        )
        attribution_context = self._get_attribution_context(performance=performance)
        return _recommendation_tracking_payload(
            recommendation_id=recommendation_id,
            recommendation=recommendation,
            execution_links=execution_links,
            performance=performance,
            lookup_error=lookup_error,
            attribution_context=attribution_context,
        )

    def _get_attribution_context(self, *, performance: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.attribution_context_provider.get_context(
                recommendation_date=_date_from_any(performance.get("anchor_date")),
                outcome_date=_performance_outcome_date(performance),
            )
        except Exception as exc:
            return {
                "recommendation": {
                    "status": "LOOKUP_FAILED",
                    "date": performance.get("anchor_date"),
                    "errors": [str(exc)],
                },
                "outcome": {
                    "status": "LOOKUP_FAILED",
                    "date": None,
                    "errors": [str(exc)],
                },
            }
