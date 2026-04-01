"""Dependency builders for decision rhythm interface views."""

from __future__ import annotations

from dataclasses import dataclass

from apps.alpha_trigger.infrastructure.repositories import get_candidate_repository
from apps.beta_gate.infrastructure.repositories import get_config_repository
from apps.simulated_trading.infrastructure.repositories import (
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)

from ..application.management_workflows import (
    GetTrendDataUseCase,
    ResetQuotaByAccountUseCase,
)
from ..application.page_workflows import (
    GetDecisionQuotaConfigPageUseCase,
    GetDecisionQuotaPageUseCase,
)
from ..application.query_workflows import (
    GetActiveCooldownByAssetUseCase,
    GetCooldownRemainingHoursUseCase,
    GetDecisionQuotaByPeriodUseCase,
    GetDecisionRequestStatisticsUseCase,
    GetDecisionRequestUseCase,
    ListActiveCooldownsUseCase,
    ListDecisionQuotasUseCase,
    ListDecisionRequestsUseCase,
)
from ..application.submit_workflows import (
    SubmitBatchWorkflowUseCase,
    SubmitDecisionWorkflowUseCase,
)
from ..application.use_cases import (
    CancelDecisionRequestUseCase,
    ExecuteDecisionUseCase,
    GetRhythmSummaryUseCase,
    PrecheckDecisionUseCase,
    SubmitBatchRequestUseCase,
    SubmitDecisionRequestUseCase,
    UpdateQuotaConfigUseCase,
)
from ..domain.services import CooldownManager, QuotaManager, RhythmManager
from ..infrastructure.repositories import (
    UnifiedRecommendationRepository,
    get_cooldown_repository,
    get_quota_repository,
    get_request_repository,
)
from shared.infrastructure.asset_name_resolver import resolve_asset_names


def _build_rhythm_manager() -> RhythmManager:
    """Build a rhythm manager for submit and summary workflows."""
    return RhythmManager(QuotaManager(), CooldownManager())


def build_submit_decision_workflow_use_case() -> SubmitDecisionWorkflowUseCase:
    """Build the legacy single-submit workflow use case."""
    return SubmitDecisionWorkflowUseCase(
        submit_use_case=SubmitDecisionRequestUseCase(_build_rhythm_manager()),
        request_repo=get_request_repository(),
        recommendation_repo=UnifiedRecommendationRepository(),
        candidate_repo=get_candidate_repository(),
    )


def build_submit_batch_workflow_use_case() -> SubmitBatchWorkflowUseCase:
    """Build the batch submit workflow use case."""
    return SubmitBatchWorkflowUseCase(
        submit_use_case=SubmitBatchRequestUseCase(_build_rhythm_manager()),
        request_repo=get_request_repository(),
    )


def build_get_rhythm_summary_use_case() -> GetRhythmSummaryUseCase:
    """Build the rhythm summary query use case."""
    return GetRhythmSummaryUseCase(_build_rhythm_manager())


def build_reset_quota_by_account_use_case() -> ResetQuotaByAccountUseCase:
    """Build the account-aware quota reset workflow use case."""
    return ResetQuotaByAccountUseCase(get_quota_repository())


def build_get_trend_data_use_case() -> GetTrendDataUseCase:
    """Build the trend data query use case."""
    return GetTrendDataUseCase(get_quota_repository())


def build_list_decision_quotas_use_case() -> ListDecisionQuotasUseCase:
    """Build the quota list query use case."""
    return ListDecisionQuotasUseCase(get_quota_repository())


def build_get_decision_quota_by_period_use_case() -> GetDecisionQuotaByPeriodUseCase:
    """Build the single-quota query use case."""
    return GetDecisionQuotaByPeriodUseCase(get_quota_repository())


def build_list_active_cooldowns_use_case() -> ListActiveCooldownsUseCase:
    """Build the active cooldown list query use case."""
    return ListActiveCooldownsUseCase(get_cooldown_repository())


def build_get_active_cooldown_by_asset_use_case() -> GetActiveCooldownByAssetUseCase:
    """Build the asset-specific cooldown query use case."""
    return GetActiveCooldownByAssetUseCase(get_cooldown_repository())


def build_get_cooldown_remaining_hours_use_case() -> GetCooldownRemainingHoursUseCase:
    """Build the remaining-hours cooldown query use case."""
    return GetCooldownRemainingHoursUseCase(get_cooldown_repository())


def build_list_decision_requests_use_case() -> ListDecisionRequestsUseCase:
    """Build the request list query use case."""
    return ListDecisionRequestsUseCase(get_request_repository())


def build_get_decision_request_use_case() -> GetDecisionRequestUseCase:
    """Build the single-request query use case."""
    return GetDecisionRequestUseCase(get_request_repository())


def build_get_decision_request_statistics_use_case() -> GetDecisionRequestStatisticsUseCase:
    """Build the request statistics query use case."""
    return GetDecisionRequestStatisticsUseCase(get_request_repository())


def build_get_decision_quota_page_use_case() -> GetDecisionQuotaPageUseCase:
    """Build the quota overview page workflow use case."""
    return GetDecisionQuotaPageUseCase(
        account_repo=DjangoSimulatedAccountRepository(),
        quota_repo=get_quota_repository(),
        cooldown_repo=get_cooldown_repository(),
        request_repo=get_request_repository(),
        asset_name_resolver=resolve_asset_names,
    )


def build_get_decision_quota_config_page_use_case() -> GetDecisionQuotaConfigPageUseCase:
    """Build the quota config page workflow use case."""
    return GetDecisionQuotaConfigPageUseCase(
        account_repo=DjangoSimulatedAccountRepository(),
        quota_repo=get_quota_repository(),
    )


def build_precheck_decision_use_case() -> PrecheckDecisionUseCase:
    """Build the decision precheck use case."""
    return PrecheckDecisionUseCase(
        beta_gate_repo=get_config_repository(),
        candidate_repo=get_candidate_repository(),
        quota_repo=get_quota_repository(),
        cooldown_repo=get_cooldown_repository(),
    )


@dataclass
class ExecuteDecisionDependencies:
    """Execution dependencies exposed to the interface layer."""

    request_repo: object
    use_case: ExecuteDecisionUseCase


def build_execute_decision_dependencies() -> ExecuteDecisionDependencies:
    """Build repositories and the execute decision use case."""
    request_repo = get_request_repository()
    return ExecuteDecisionDependencies(
        request_repo=request_repo,
        use_case=ExecuteDecisionUseCase(
            request_repo=request_repo,
            candidate_repo=get_candidate_repository(),
            simulated_account_repo=DjangoSimulatedAccountRepository(),
            position_repo=DjangoPositionRepository(),
            trade_repo=DjangoTradeRepository(),
        ),
    )


def build_cancel_decision_request_use_case() -> CancelDecisionRequestUseCase:
    """Build the cancel decision use case."""
    return CancelDecisionRequestUseCase(
        request_repo=get_request_repository(),
        candidate_repo=get_candidate_repository(),
    )


def build_update_quota_config_use_case() -> UpdateQuotaConfigUseCase:
    """Build the quota config update use case."""
    return UpdateQuotaConfigUseCase(get_quota_repository())
