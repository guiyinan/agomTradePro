"""Decision Rhythm repository provider for application consumers."""

from __future__ import annotations

from apps.decision_rhythm.infrastructure.feature_providers import (  # noqa: F401
    create_candidate_provider,
    create_feature_provider,
    create_signal_provider,
    create_valuation_provider,
)
from apps.decision_rhythm.infrastructure.providers import (
    CooldownRepository,
    DecisionModelParamConfigRepository,
    DecisionRequestRepository,
    ExecutionApprovalRequestRepository,
    InvestmentRecommendationRepository,
    PortfolioTransitionPlanRepository,
    QuotaRepository,
    UnifiedRecommendationRepository,
    ValuationSnapshotRepository,
    get_request_repository,
)


def get_decision_request_repository() -> DecisionRequestRepository:
    """Return the Decision Request repository."""

    return get_request_repository()


def get_quota_repository() -> QuotaRepository:
    return QuotaRepository()


def get_cooldown_repository() -> CooldownRepository:
    return CooldownRepository()


def get_execution_approval_request_repository() -> ExecutionApprovalRequestRepository:
    return ExecutionApprovalRequestRepository()


def get_investment_recommendation_repository() -> InvestmentRecommendationRepository:
    return InvestmentRecommendationRepository()


def get_portfolio_transition_plan_repository() -> PortfolioTransitionPlanRepository:
    return PortfolioTransitionPlanRepository()


def get_unified_recommendation_repository() -> UnifiedRecommendationRepository:
    return UnifiedRecommendationRepository()


def get_valuation_snapshot_repository() -> ValuationSnapshotRepository:
    return ValuationSnapshotRepository()


def get_decision_model_param_config_repository() -> DecisionModelParamConfigRepository:
    return DecisionModelParamConfigRepository()
