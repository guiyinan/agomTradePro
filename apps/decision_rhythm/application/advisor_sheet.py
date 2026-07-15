"""Public use case that composes the account-level advisor decision sheet."""

from __future__ import annotations

from typing import Any

from apps.decision_rhythm.application.advisor_contracts import (
    BUY_SIDES,
    AdvisorOrderIntent,
    AttributionContextProviderProtocol,
    DataHealthProviderProtocol,
    ExecutionGuardProviderProtocol,
    ExposureProviderProtocol,
    HoldingSnapshotProviderProtocol,
    RecommendationPerformanceProviderProtocol,
    RecommendationProviderProtocol,
    RecommendationTrackingProviderProtocol,
    RiskGateProviderProtocol,
)
from apps.decision_rhythm.application.advisor_execution import (
    _build_advisor_execution_plan,
    _build_allocation_payload,
    _build_exposure_summary,
    _build_next_actions,
    _build_order_summary,
    _build_risk_summary,
    _resolve_missing_names,
    _resolve_verdict,
)
from apps.decision_rhythm.application.advisor_intents import (
    _data_health_warnings,
    _normalize_recommendation_side,
    _recommendation_asset_code,
    _unique_asset_codes,
)
from apps.decision_rhythm.application.advisor_performance import (
    _attach_recommendation_resolution,
    _consolidate_recommendations,
    _find_recommendation_for_asset,
)
from apps.decision_rhythm.application.advisor_providers import (
    AccountHoldingSnapshotProvider,
    DataCenterAssetExposureProvider,
    DataCenterRecommendationPerformanceProvider,
    DecisionDataHealthProvider,
    DecisionExecutionTrackingProvider,
    DecisionRhythmExecutionGuardProvider,
    RegimePolicyAttributionContextProvider,
    RiskCenterAdvisorGateProvider,
    WorkspaceRecommendationProvider,
)
from apps.decision_rhythm.application.advisor_serialization import (
    _now_iso,
    _to_decimal,
)
from apps.decision_rhythm.application.advisor_sheet_context import AdvisorSheetContextMixin
from apps.decision_rhythm.application.advisor_sheet_intents import AdvisorSheetIntentMixin


class GenerateAdvisorDecisionSheetUseCase(AdvisorSheetContextMixin, AdvisorSheetIntentMixin):
    """Generate a read-only account-level advisor decision sheet."""

    def __init__(
        self,
        *,
        holding_provider: HoldingSnapshotProviderProtocol | None = None,
        recommendation_provider: RecommendationProviderProtocol | None = None,
        risk_gate_provider: RiskGateProviderProtocol | None = None,
        data_health_provider: DataHealthProviderProtocol | None = None,
        execution_guard_provider: ExecutionGuardProviderProtocol | None = None,
        exposure_provider: ExposureProviderProtocol | None = None,
        tracking_provider: RecommendationTrackingProviderProtocol | None = None,
        performance_provider: RecommendationPerformanceProviderProtocol | None = None,
        attribution_context_provider: AttributionContextProviderProtocol | None = None,
    ) -> None:
        self.holding_provider = holding_provider or AccountHoldingSnapshotProvider()
        self.recommendation_provider = recommendation_provider or WorkspaceRecommendationProvider()
        self.risk_gate_provider = risk_gate_provider or RiskCenterAdvisorGateProvider()
        self.data_health_provider = data_health_provider or DecisionDataHealthProvider()
        self.execution_guard_provider = (
            execution_guard_provider or DecisionRhythmExecutionGuardProvider()
        )
        self.exposure_provider = exposure_provider or DataCenterAssetExposureProvider()
        self.tracking_provider = tracking_provider or DecisionExecutionTrackingProvider()
        self.performance_provider = (
            performance_provider or DataCenterRecommendationPerformanceProvider()
        )
        self.attribution_context_provider = (
            attribution_context_provider or RegimePolicyAttributionContextProvider()
        )

    def execute(self, *, account_id: str, user: Any) -> dict[str, Any]:
        """Generate holdings, allocation drift, order intents, blockers, and actions."""

        snapshot = self.holding_provider.get_snapshot(account_id=account_id, user=user)
        account = snapshot.account_summary
        total_asset = _to_decimal(account.get("total_asset"))
        cash = _to_decimal(account.get("available_cash"))
        holdings = sorted(snapshot.holdings, key=lambda item: item.current_weight, reverse=True)
        holdings_by_code = {item.asset_code: item for item in holdings}

        raw_recommendations = self.recommendation_provider.list_recommendations(
            account_id=str(account["account_id"])
        )
        recommendation_resolution = _consolidate_recommendations(
            raw_recommendations,
            held_asset_codes=set(holdings_by_code),
        )
        recommendations = recommendation_resolution["selected_recommendations"]
        resolutions_by_asset = recommendation_resolution["resolutions_by_asset"]
        recommendation_conflicts = recommendation_resolution["conflicts"]
        security_names = _resolve_missing_names(holdings, raw_recommendations)
        candidate_codes = _unique_asset_codes(
            [
                *(holding.asset_code for holding in holdings),
                *(_recommendation_asset_code(item) for item in raw_recommendations),
            ]
        )

        blockers: list[dict[str, Any]] = []
        warnings = list(snapshot.warnings)
        order_intents: list[AdvisorOrderIntent] = []
        risk_policy = self._get_risk_policy_context(account_id=str(account["account_id"]))
        data_health = self._get_data_health(asset_codes=candidate_codes)
        exposure_map = self._get_exposure_map(asset_codes=candidate_codes)

        for holding in holdings:
            rec = _find_recommendation_for_asset(recommendations, holding.asset_code)
            intent = self._build_existing_holding_intent(
                account_id=str(account["account_id"]),
                holding=holding,
                total_asset=total_asset,
                recommendation=rec,
            )
            if intent is not None:
                intent = _attach_recommendation_resolution(
                    intent,
                    resolutions_by_asset.get(holding.asset_code),
                )
                intent = self._apply_execution_guard(
                    intent=intent,
                    recommendation=rec,
                    resolution=resolutions_by_asset.get(holding.asset_code),
                )
                order_intents.append(
                    self._apply_risk_gate(
                        account=account,
                        holdings=holdings,
                        order_intents=[intent],
                        policy_context=risk_policy,
                    )[0]
                )

        remaining_cash = cash
        for recommendation in recommendations:
            asset_code = _recommendation_asset_code(recommendation)
            if not asset_code:
                continue
            side = _normalize_recommendation_side(recommendation)
            if side not in BUY_SIDES:
                continue
            if asset_code in holdings_by_code and any(
                item.asset_code == asset_code and item.side in {"ADD", "BUY"}
                for item in order_intents
            ):
                continue
            if _to_decimal(getattr(recommendation, "suggested_quantity", 0)) == 0:
                warnings.append(f"{asset_code}:recommendation_quantity_zero_recomputed")

            current_holding = holdings_by_code.get(asset_code)
            intent = self._build_buy_intent(
                account_id=str(account["account_id"]),
                recommendation=recommendation,
                holding=current_holding,
                total_asset=total_asset,
                available_cash=remaining_cash,
                asset_name=security_names.get(asset_code, asset_code),
                baseline=snapshot.baseline,
            )
            if intent is None:
                continue
            intent = _attach_recommendation_resolution(
                intent,
                resolutions_by_asset.get(asset_code),
            )
            intent = self._apply_execution_guard(
                intent=intent,
                recommendation=recommendation,
                resolution=resolutions_by_asset.get(asset_code),
            )
            gated_intent = self._apply_risk_gate(
                account=account,
                holdings=holdings,
                order_intents=[intent],
                policy_context=risk_policy,
            )[0]
            order_intents.append(gated_intent)
            if gated_intent.blocking_status == "OK":
                remaining_cash -= gated_intent.estimated_amount

        exposure_summary = _build_exposure_summary(
            holdings=holdings,
            order_intents=order_intents,
            exposure_map=exposure_map,
            recommendations=raw_recommendations,
            total_asset=total_asset,
            policy_context=risk_policy,
        )
        order_intents = self._apply_exposure_guard(
            order_intents=order_intents,
            exposure_summary=exposure_summary,
        )
        tracking_map = self._get_recommendation_tracking(
            account_id=str(account["account_id"]),
            order_intents=order_intents,
            recommendations=raw_recommendations,
            user=user,
        )
        order_intents = self._attach_tracking_context(
            order_intents=order_intents,
            tracking_map=tracking_map,
        )
        order_intents = self._attach_confirmation_context(
            account=account,
            order_intents=order_intents,
            data_health=data_health,
            policy_context=risk_policy,
        )
        order_intents = self._attach_decision_card_context(
            order_intents=order_intents,
            data_health=data_health,
        )
        order_intents = sorted(order_intents, key=lambda item: (item.priority, item.asset_code))
        for intent in order_intents:
            if intent.blocking_status != "OK":
                blockers.append(
                    {
                        "type": intent.blocking_status,
                        "asset_code": intent.asset_code,
                        "message": "；".join(intent.risk_notes) or "订单意图存在阻断项",
                    }
                )

        allocation = _build_allocation_payload(holdings, total_asset=total_asset)
        if data_health.get("must_not_use_for_decision"):
            warnings.extend(_data_health_warnings(data_health))
        if recommendation_conflicts:
            warnings.extend(
                f"recommendation_conflict:{item['asset_code']}:{item['conflict_reason']}"
                for item in recommendation_conflicts
            )
        verdict = _resolve_verdict(
            order_intents=order_intents,
            blockers=blockers,
            warnings=warnings,
            data_health_blocked=bool(data_health.get("must_not_use_for_decision")),
            has_recommendation_conflicts=bool(recommendation_conflicts),
        )
        next_actions = _build_next_actions(verdict=verdict, has_orders=bool(order_intents))
        order_payloads = [intent.to_dict() for intent in order_intents]
        execution_plan = _build_advisor_execution_plan(
            account=account,
            order_payloads=order_payloads,
            verdict=verdict,
            data_health=data_health,
        )

        return {
            "account": account,
            "baseline": snapshot.baseline,
            "generated_at": _now_iso(),
            "today_conclusion": verdict,
            "risk_policy": risk_policy,
            "data_health": data_health,
            "exposure_summary": exposure_summary,
            "risk_summary": _build_risk_summary(
                holdings,
                blockers,
                warnings,
                exposure_summary=exposure_summary,
            ),
            "holdings": [holding.to_dict() for holding in holdings],
            "allocation": allocation,
            "order_summary": _build_order_summary(order_intents),
            "order_intents": order_payloads,
            "decision_cards": [item["decision_card"] for item in order_payloads],
            "execution_plan": execution_plan,
            "recommendation_conflicts": recommendation_conflicts,
            "blockers": blockers,
            "warnings": warnings,
            "next_actions": next_actions,
        }


__all__ = ["GenerateAdvisorDecisionSheetUseCase"]
