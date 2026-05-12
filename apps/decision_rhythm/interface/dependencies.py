"""Dependency builders for decision rhythm interface views."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

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


def _decision_rhythm_repository_module():
    return import_module("apps.decision_rhythm.infrastructure.repositories")


def _candidate_repository():
    return import_module("apps.alpha_trigger.infrastructure.repositories").get_candidate_repository()


def _beta_gate_repository():
    return import_module("apps.beta_gate.infrastructure.repositories").get_config_repository()


def _simulated_trading_repository_module():
    return import_module("apps.simulated_trading.infrastructure.repositories")


def _account_repository():
    return _simulated_trading_repository_module().DjangoSimulatedAccountRepository()


def _position_repository():
    return _simulated_trading_repository_module().DjangoPositionRepository()


def _trade_repository():
    return _simulated_trading_repository_module().DjangoTradeRepository()


def _signal_repository():
    return import_module("apps.signal.infrastructure.repositories").DjangoSignalRepository()


def _request_repository():
    return _decision_rhythm_repository_module().get_request_repository()


def _quota_repository():
    return _decision_rhythm_repository_module().get_quota_repository()


def _cooldown_repository():
    return _decision_rhythm_repository_module().get_cooldown_repository()


def _recommendation_repository():
    return _decision_rhythm_repository_module().UnifiedRecommendationRepository()


def _resolve_asset_names(values):
    return import_module("apps.asset_analysis.application.asset_name_service").resolve_asset_names(
        values
    )


def _build_rhythm_manager() -> RhythmManager:
    """Build a rhythm manager for submit and summary workflows."""
    return RhythmManager(QuotaManager(), CooldownManager())


def build_submit_decision_workflow_use_case() -> SubmitDecisionWorkflowUseCase:
    """Build the legacy single-submit workflow use case."""
    return SubmitDecisionWorkflowUseCase(
        submit_use_case=SubmitDecisionRequestUseCase(_build_rhythm_manager()),
        request_repo=_request_repository(),
        recommendation_repo=_recommendation_repository(),
        candidate_repo=_candidate_repository(),
    )


def build_submit_batch_workflow_use_case() -> SubmitBatchWorkflowUseCase:
    """Build the batch submit workflow use case."""
    return SubmitBatchWorkflowUseCase(
        submit_use_case=SubmitBatchRequestUseCase(_build_rhythm_manager()),
        request_repo=_request_repository(),
    )


def build_get_rhythm_summary_use_case() -> GetRhythmSummaryUseCase:
    """Build the rhythm summary query use case."""
    return GetRhythmSummaryUseCase(_build_rhythm_manager())


def build_reset_quota_by_account_use_case() -> ResetQuotaByAccountUseCase:
    """Build the account-aware quota reset workflow use case."""
    return ResetQuotaByAccountUseCase(_quota_repository())


def build_get_trend_data_use_case() -> GetTrendDataUseCase:
    """Build the trend data query use case."""
    return GetTrendDataUseCase(_quota_repository())


def build_list_decision_quotas_use_case() -> ListDecisionQuotasUseCase:
    """Build the quota list query use case."""
    return ListDecisionQuotasUseCase(_quota_repository())


def build_get_decision_quota_by_period_use_case() -> GetDecisionQuotaByPeriodUseCase:
    """Build the single-quota query use case."""
    return GetDecisionQuotaByPeriodUseCase(_quota_repository())


def build_list_active_cooldowns_use_case() -> ListActiveCooldownsUseCase:
    """Build the active cooldown list query use case."""
    return ListActiveCooldownsUseCase(_cooldown_repository())


def build_get_active_cooldown_by_asset_use_case() -> GetActiveCooldownByAssetUseCase:
    """Build the asset-specific cooldown query use case."""
    return GetActiveCooldownByAssetUseCase(_cooldown_repository())


def build_get_cooldown_remaining_hours_use_case() -> GetCooldownRemainingHoursUseCase:
    """Build the remaining-hours cooldown query use case."""
    return GetCooldownRemainingHoursUseCase(_cooldown_repository())


def build_list_decision_requests_use_case() -> ListDecisionRequestsUseCase:
    """Build the request list query use case."""
    return ListDecisionRequestsUseCase(_request_repository())


def build_get_decision_request_use_case() -> GetDecisionRequestUseCase:
    """Build the single-request query use case."""
    return GetDecisionRequestUseCase(_request_repository())


def build_get_decision_request_statistics_use_case() -> GetDecisionRequestStatisticsUseCase:
    """Build the request statistics query use case."""
    return GetDecisionRequestStatisticsUseCase(_request_repository())


def build_get_decision_quota_page_use_case() -> GetDecisionQuotaPageUseCase:
    """Build the quota overview page workflow use case."""
    return GetDecisionQuotaPageUseCase(
        account_repo=_account_repository(),
        quota_repo=_quota_repository(),
        cooldown_repo=_cooldown_repository(),
        request_repo=_request_repository(),
        asset_name_resolver=_resolve_asset_names,
    )


def build_get_decision_quota_config_page_use_case() -> GetDecisionQuotaConfigPageUseCase:
    """Build the quota config page workflow use case."""
    return GetDecisionQuotaConfigPageUseCase(
        account_repo=_account_repository(),
        quota_repo=_quota_repository(),
    )


def build_precheck_decision_use_case() -> PrecheckDecisionUseCase:
    """Build the decision precheck use case."""
    return PrecheckDecisionUseCase(
        beta_gate_repo=_beta_gate_repository(),
        candidate_repo=_candidate_repository(),
        quota_repo=_quota_repository(),
        cooldown_repo=_cooldown_repository(),
    )


@dataclass
class ExecuteDecisionDependencies:
    """Execution dependencies exposed to the interface layer."""

    request_repo: object
    use_case: ExecuteDecisionUseCase


def build_execute_decision_dependencies() -> ExecuteDecisionDependencies:
    """Build repositories and the execute decision use case."""
    request_repo = _request_repository()
    return ExecuteDecisionDependencies(
        request_repo=request_repo,
        use_case=ExecuteDecisionUseCase(
            request_repo=request_repo,
            candidate_repo=_candidate_repository(),
            simulated_account_repo=_account_repository(),
            position_repo=_position_repository(),
            trade_repo=_trade_repository(),
            signal_repo=_signal_repository(),
        ),
    )


def build_cancel_decision_request_use_case() -> CancelDecisionRequestUseCase:
    """Build the cancel decision use case."""
    return CancelDecisionRequestUseCase(
        request_repo=_request_repository(),
        candidate_repo=_candidate_repository(),
    )


def build_update_quota_config_use_case() -> UpdateQuotaConfigUseCase:
    """Build the quota config update use case."""
    return UpdateQuotaConfigUseCase(_quota_repository())
