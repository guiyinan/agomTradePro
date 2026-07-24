"""Tests for decision-rhythm backed simulated-trading exit advice."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from apps.decision_rhythm.application.exit_advisors import DecisionRhythmExitAdvisor
from apps.decision_rhythm.domain.entities import (
    PortfolioTransitionPlan,
    TransitionOrder,
    UnifiedRecommendation,
)


class _RecommendationRepository:
    def __init__(self, recommendations: list[UnifiedRecommendation]) -> None:
        self.recommendations = recommendations

    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list[UnifiedRecommendation]:
        return self.recommendations


class _FailingRecommendationRepository:
    def get_by_account(
        self,
        account_id: str,
        status: str | None = None,
    ) -> list[UnifiedRecommendation]:
        raise RuntimeError("recommendation store unavailable")


class _TransitionPlanRepository:
    def __init__(self, plan: PortfolioTransitionPlan | None) -> None:
        self.plan = plan

    def get_latest_for_account(self, account_id: str) -> PortfolioTransitionPlan | None:
        return self.plan


def test_matches_recommendation_security_codes_case_insensitively() -> None:
    recommendation = UnifiedRecommendation(
        recommendation_id="recommendation-1",
        account_id="1",
        security_code="000001.sz",
        side="SELL",
        human_rationale="risk regime changed",
        target_price_low=Decimal("9.50"),
        target_price_high=Decimal("10.50"),
        stop_loss_price=Decimal("9.00"),
    )
    advisor = DecisionRhythmExitAdvisor(
        recommendation_repo=_RecommendationRepository([recommendation]),
        transition_plan_repo=_TransitionPlanRepository(None),
    )

    advices = advisor.get_exit_advices(
        account_id=1,
        positions=[SimpleNamespace(asset_code="000001.SZ", quantity=100)],
        as_of_date=date(2026, 7, 24),
    )

    assert len(advices) == 1
    assert advices[0].asset_code == "000001.SZ"
    assert advices[0].should_exit is True
    assert advices[0].quantity == 100
    assert advices[0].recommendation_id == "recommendation-1"


def test_uses_transition_plan_when_recommendation_source_fails() -> None:
    order = TransitionOrder(
        security_code="000001.sz",
        action="EXIT",
        current_qty=100,
        target_qty=0,
        delta_qty=-100,
        current_weight=0.1,
        target_weight=0.0,
        price_band_low=Decimal("9.50"),
        price_band_high=Decimal("10.50"),
        max_capital=Decimal("1000"),
        stop_loss_price=Decimal("9.00"),
        invalidation_rule={"conditions": ["risk regime changed"]},
        invalidation_description="risk exit",
    )
    plan = PortfolioTransitionPlan(
        plan_id="plan-1",
        account_id="1",
        as_of=datetime(2026, 7, 24, 8, tzinfo=UTC),
        source_recommendation_ids=[],
        current_positions_snapshot=[],
        target_positions_snapshot=[],
        orders=[order],
        risk_contract={},
        summary={},
    )
    advisor = DecisionRhythmExitAdvisor(
        recommendation_repo=_FailingRecommendationRepository(),
        transition_plan_repo=_TransitionPlanRepository(plan),
    )

    advices = advisor.get_exit_advices(
        account_id=1,
        positions=[SimpleNamespace(asset_code="000001.SZ", quantity=100)],
        as_of_date=date(2026, 7, 24),
    )

    assert len(advices) == 1
    assert advices[0].asset_code == "000001.SZ"
    assert advices[0].reason_code == "TRANSITION_PLAN_EXIT"
    assert advices[0].quantity == 100
