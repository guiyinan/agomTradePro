"""Decision Rhythm repository provider for application consumers."""

from __future__ import annotations

from typing import Any

from apps.decision_rhythm.infrastructure.feature_providers import (
    create_candidate_provider as create_candidate_provider,
)
from apps.decision_rhythm.infrastructure.feature_providers import (
    create_feature_provider as create_feature_provider,
)
from apps.decision_rhythm.infrastructure.feature_providers import (
    create_signal_provider as create_signal_provider,
)
from apps.decision_rhythm.infrastructure.feature_providers import (
    create_valuation_provider as create_valuation_provider,
)
from apps.decision_rhythm.infrastructure.providers import (
    CooldownRepository as CooldownRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    DecisionModelParamConfigRepository as DecisionModelParamConfigRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    DecisionRequestRepository as DecisionRequestRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    ExecutionApprovalRequestRepository as ExecutionApprovalRequestRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    InvestmentRecommendationRepository as InvestmentRecommendationRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    PortfolioTransitionPlanRepository as PortfolioTransitionPlanRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    QuotaRepository as QuotaRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    UnifiedRecommendationRepository as UnifiedRecommendationRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
    ValuationSnapshotRepository as ValuationSnapshotRepository,
)
from apps.decision_rhythm.infrastructure.providers import (
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


def check_alpha_workspace_consistency_health() -> dict[str, Any]:
    """Return Alpha/workspace consistency health from the infrastructure provider."""

    from apps.decision_rhythm.infrastructure.consistency_snapshots import (
        check_alpha_workspace_consistency_health as _check_health,
    )

    return _check_health()


def list_share_decisions_for_account_assets(
    *, account_id: int, asset_codes: set[str], limit: int = 12
) -> list[Any]:
    """Return Decision Rhythm rows used by Share snapshot rendering."""

    from apps.decision_rhythm.infrastructure.share_query_repository import (
        list_share_decisions_for_account_assets as _list_share_decisions,
    )

    return _list_share_decisions(
        account_id=account_id,
        asset_codes=asset_codes,
        limit=limit,
    )


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
    "check_alpha_workspace_consistency_health",
    "create_candidate_provider",
    "create_feature_provider",
    "create_signal_provider",
    "create_valuation_provider",
    "get_cooldown_repository",
    "get_decision_model_param_config_repository",
    "get_decision_request_repository",
    "get_execution_approval_request_repository",
    "get_investment_recommendation_repository",
    "get_portfolio_transition_plan_repository",
    "get_quota_repository",
    "get_unified_recommendation_repository",
    "get_valuation_snapshot_repository",
    "list_share_decisions_for_account_assets",
]
