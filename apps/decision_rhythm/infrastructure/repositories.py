"""Stable repository import surface for Decision Rhythm infrastructure."""

from __future__ import annotations

from .recommendation_repositories import (
    ExecutionApprovalRequestRepository,
    InvestmentRecommendationRepository,
    PortfolioTransitionPlanRepository,
    ValuationSnapshotRepository,
)
from .rhythm_repositories import (
    CooldownRepository,
    DecisionRequestRepository,
    QuotaRepository,
    get_cooldown_repository,
    get_quota_repository,
    get_request_repository,
)
from .unified_repositories import (
    DecisionModelParamConfigRepository,
    UnifiedRecommendationRepository,
)


def get_valuation_snapshot_repository() -> ValuationSnapshotRepository:
    """Return the valuation snapshot repository."""

    return ValuationSnapshotRepository()


def get_investment_recommendation_repository() -> InvestmentRecommendationRepository:
    """Return the investment recommendation repository."""

    return InvestmentRecommendationRepository()


def get_execution_approval_request_repository() -> ExecutionApprovalRequestRepository:
    """Return the execution approval request repository."""

    return ExecutionApprovalRequestRepository()


def get_portfolio_transition_plan_repository() -> PortfolioTransitionPlanRepository:
    """Return the portfolio transition plan repository."""

    return PortfolioTransitionPlanRepository()


__all__ = [
    "CooldownRepository",
    "DecisionModelParamConfigRepository",
    "DecisionRequestRepository",
    "ExecutionApprovalRequestRepository",
    "InvestmentRecommendationRepository",
    "PortfolioTransitionPlanRepository",
    "QuotaRepository",
    "UnifiedRecommendationRepository",
    "ValuationSnapshotRepository",
    "get_cooldown_repository",
    "get_execution_approval_request_repository",
    "get_investment_recommendation_repository",
    "get_portfolio_transition_plan_repository",
    "get_quota_repository",
    "get_request_repository",
    "get_valuation_snapshot_repository",
]
