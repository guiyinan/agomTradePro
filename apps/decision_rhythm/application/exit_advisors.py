"""Decision-rhythm backed exit advisors for simulated trading."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from apps.decision_rhythm.application.repository_provider import (
    get_portfolio_transition_plan_repository,
    get_unified_recommendation_repository,
)
from apps.simulated_trading.application.ports import (
    PositionExitAdvice,
    PositionExitAdvisorProtocol,
)

if TYPE_CHECKING:
    from apps.decision_rhythm.domain.entities import PortfolioTransitionPlan, UnifiedRecommendation


logger = logging.getLogger(__name__)


class DecisionRhythmExitAdvisor(PositionExitAdvisorProtocol):
    """Translate decision-rhythm recommendations into executable exit advice."""

    def __init__(self, recommendation_repo=None, transition_plan_repo=None):
        self.recommendation_repo = recommendation_repo or get_unified_recommendation_repository()
        self.transition_plan_repo = transition_plan_repo or get_portfolio_transition_plan_repository()

    def get_exit_advices(
        self,
        account_id: int,
        positions: list[object],
        as_of_date: date,
    ) -> list[PositionExitAdvice]:
        if not positions:
            return []

        try:
            recommendations = self.recommendation_repo.get_by_account(str(account_id))
        except Exception as exc:
            logger.warning("Failed to load unified recommendations for account %s: %s", account_id, exc)
            recommendations = []

        recommendation_map = self._latest_recommendations_by_security(recommendations)
        transition_plan = self._get_current_transition_plan(account_id, as_of_date)
        transition_order_map = {
            order.security_code: order for order in getattr(transition_plan, "orders", [])
        }

        advices: list[PositionExitAdvice] = []
        for position in positions:
            asset_code = str(getattr(position, "asset_code", "") or "").strip()
            if not asset_code:
                continue

            order = transition_order_map.get(asset_code)
            if order and order.action in {"EXIT", "REDUCE"} and order.is_ready_for_approval:
                quantity = abs(int(order.delta_qty)) if order.delta_qty else None
                advices.append(
                    PositionExitAdvice(
                        asset_code=asset_code,
                        should_exit=order.action == "EXIT",
                        should_reduce=order.action == "REDUCE",
                        quantity=quantity,
                        reason_code=f"TRANSITION_PLAN_{order.action}",
                        reason_text=order.invalidation_description or f"调仓计划建议{order.action}",
                        source="decision_rhythm.transition_plan",
                    )
                )
                continue

            recommendation = recommendation_map.get(asset_code)
            if recommendation and str(getattr(recommendation, "side", "")).upper() == "SELL":
                advices.append(
                    PositionExitAdvice(
                        asset_code=asset_code,
                        should_exit=True,
                        quantity=int(getattr(position, "quantity", 0) or 0),
                        reason_code="UNIFIED_RECOMMENDATION_SELL",
                        reason_text=getattr(recommendation, "human_rationale", "") or "统一推荐转为 SELL",
                        source="decision_rhythm.recommendation",
                    )
                )

        return advices

    def _get_current_transition_plan(
        self,
        account_id: int,
        as_of_date: date,
    ) -> "PortfolioTransitionPlan" | None:
        try:
            plan = self.transition_plan_repo.get_latest_for_account(str(account_id))
        except Exception as exc:
            logger.warning("Failed to load transition plan for account %s: %s", account_id, exc)
            return None

        if plan is None:
            return None

        plan_date = getattr(getattr(plan, "as_of", None), "date", lambda: None)()
        return plan if plan_date == as_of_date else None

    def _latest_recommendations_by_security(
        self,
        recommendations: list["UnifiedRecommendation"],
    ) -> dict[str, "UnifiedRecommendation"]:
        latest_by_security: dict[str, "UnifiedRecommendation"] = {}
        for recommendation in recommendations:
            security_code = str(getattr(recommendation, "security_code", "") or "").strip()
            if not security_code:
                continue

            current = latest_by_security.get(security_code)
            if current is None:
                latest_by_security[security_code] = recommendation
                continue

            current_time = getattr(current, "updated_at", None) or getattr(current, "created_at", None)
            next_time = getattr(recommendation, "updated_at", None) or getattr(
                recommendation, "created_at", None
            )
            if next_time and (current_time is None or next_time >= current_time):
                latest_by_security[security_code] = recommendation

        return latest_by_security


def build_decision_rhythm_exit_advisor() -> PositionExitAdvisorProtocol:
    """Build the default exit advisor backed by decision rhythm outputs."""

    return DecisionRhythmExitAdvisor()
