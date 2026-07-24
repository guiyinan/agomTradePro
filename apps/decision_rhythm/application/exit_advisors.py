"""Decision-rhythm backed exit advisors for simulated trading."""

from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

from django.db import DatabaseError

from apps.decision_rhythm.application.repository_provider import (
    get_portfolio_transition_plan_repository,
    get_unified_recommendation_repository,
)
from apps.decision_rhythm.domain.entities import PortfolioTransitionPlan, UnifiedRecommendation
from apps.simulated_trading.application.ports import (
    PositionExitAdvice,
    PositionExitAdvisorProtocol,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

EXIT_ADVISOR_SOURCE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    DatabaseError,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class UnifiedRecommendationRepositoryProtocol(Protocol):
    """Read unified recommendations needed by the exit advisor."""

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list[UnifiedRecommendation]:
        """Return recommendations for one account."""


class PortfolioTransitionPlanRepositoryProtocol(Protocol):
    """Read the latest transition plan needed by the exit advisor."""

    def get_latest_for_account(self, account_id: str) -> PortfolioTransitionPlan | None:
        """Return the latest transition plan for one account."""


class DecisionRhythmExitAdvisor(PositionExitAdvisorProtocol):
    """Translate decision-rhythm recommendations into executable exit advice."""

    def __init__(
        self,
        recommendation_repo: UnifiedRecommendationRepositoryProtocol | None = None,
        transition_plan_repo: PortfolioTransitionPlanRepositoryProtocol | None = None,
    ) -> None:
        self.recommendation_repo = (
            recommendation_repo
            if recommendation_repo is not None
            else get_unified_recommendation_repository()
        )
        self.transition_plan_repo = (
            transition_plan_repo
            if transition_plan_repo is not None
            else get_portfolio_transition_plan_repository()
        )

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
        except EXIT_ADVISOR_SOURCE_EXCEPTIONS as exc:
            logger.warning(
                "Failed to load unified recommendations for account %s: %s", account_id, exc
            )
            recommendations = []

        recommendation_map = self._latest_recommendations_by_security(recommendations)
        transition_plan = self._get_current_transition_plan(account_id, as_of_date)
        transition_order_map = {
            order.security_code.strip().upper(): order
            for order in (transition_plan.orders if transition_plan is not None else [])
        }

        advices: list[PositionExitAdvice] = []
        for position in positions:
            asset_code = str(getattr(position, "asset_code", "") or "").strip().upper()
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
            if recommendation and recommendation.side.upper() == "SELL":
                advices.append(
                    PositionExitAdvice(
                        asset_code=asset_code,
                        should_exit=True,
                        quantity=int(getattr(position, "quantity", 0) or 0),
                        reason_code="UNIFIED_RECOMMENDATION_SELL",
                        reason_text=recommendation.human_rationale or "统一推荐转为 SELL",
                        source="decision_rhythm.recommendation",
                        recommendation_id=recommendation.recommendation_id,
                        target_price_low=self._as_float(recommendation.target_price_low),
                        target_price_high=self._as_float(recommendation.target_price_high),
                        stop_loss_price=self._as_float(recommendation.stop_loss_price),
                    )
                )

        return advices

    def _get_current_transition_plan(
        self,
        account_id: int,
        as_of_date: date,
    ) -> PortfolioTransitionPlan | None:
        try:
            plan = self.transition_plan_repo.get_latest_for_account(str(account_id))
        except EXIT_ADVISOR_SOURCE_EXCEPTIONS as exc:
            logger.warning("Failed to load transition plan for account %s: %s", account_id, exc)
            return None

        if plan is None:
            return None

        return plan if plan.as_of.date() == as_of_date else None

    def _latest_recommendations_by_security(
        self,
        recommendations: list[UnifiedRecommendation],
    ) -> dict[str, UnifiedRecommendation]:
        latest_by_security: dict[str, UnifiedRecommendation] = {}
        for recommendation in recommendations:
            security_code = recommendation.security_code.strip().upper()
            if not security_code:
                continue

            current = latest_by_security.get(security_code)
            if current is None:
                latest_by_security[security_code] = recommendation
                continue

            if recommendation.updated_at >= current.updated_at:
                latest_by_security[security_code] = recommendation

        return latest_by_security

    @staticmethod
    def _as_float(value: object) -> float | None:
        parsed = safe_float(value)
        return parsed if parsed not in (None, 0.0) else None


def build_decision_rhythm_exit_advisor() -> PositionExitAdvisorProtocol:
    """Build the default exit advisor backed by decision rhythm outputs."""

    return DecisionRhythmExitAdvisor()
