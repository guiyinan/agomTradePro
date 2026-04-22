"""Application services for decision workspace APIs."""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

from apps.equity.application.query_services import get_valuation_repair_snapshot_map
from apps.signal.application.query_services import get_signal_invalidation_payloads
from apps.simulated_trading.application.query_services import get_position_snapshots
from apps.asset_analysis.application.asset_name_service import resolve_asset_names

from ..domain.entities import (
    ApprovalStatus,
    PortfolioTransitionPlan,
    QuotaPeriod,
    UserDecisionAction,
    create_execution_approval_request,
    create_portfolio_transition_plan,
)
from ..domain.services import RecommendationConsolidationService, ValuationSnapshotService
from ..infrastructure.feature_providers import (
    create_candidate_provider,
    create_feature_provider,
    create_signal_provider,
    create_valuation_provider,
)
from ..infrastructure.repositories import (
    CooldownRepository,
    DecisionModelParamConfigRepository,
    ExecutionApprovalRequestRepository,
    InvestmentRecommendationRepository,
    PortfolioTransitionPlanRepository,
    QuotaRepository,
    UnifiedRecommendationRepository,
    ValuationSnapshotRepository,
)
from .dtos import (
    ConflictDTO,
    RefreshRecommendationsRequestDTO,
    RefreshRecommendationsResponseDTO,
    UnifiedRecommendationDTO,
)
from .use_cases import (
    GenerateRecommendationsRequest,
    GenerateUnifiedRecommendationsUseCase,
    GetModelParamsUseCase,
    UpdateModelParamRequest,
    UpdateModelParamUseCase,
)

logger = logging.getLogger(__name__)


def _resolve_security_name_map(security_codes: list[str]) -> dict[str, str]:
    """Resolve display names for workspace security codes."""
    normalized_codes = [str(code or "").upper() for code in security_codes if str(code or "").strip()]
    if not normalized_codes:
        return {}
    return resolve_asset_names(normalized_codes)


def _attach_security_name(dto: UnifiedRecommendationDTO, security_name_map: dict[str, str]) -> UnifiedRecommendationDTO:
    """Populate DTO display name without mutating domain entities."""
    security_code = str(dto.security_code or "").upper()
    dto.security_name = security_name_map.get(security_code, dto.security_code)
    return dto


def get_valuation_repair_map(security_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Return valuation repair snapshots keyed by upper security code."""
    return get_valuation_repair_snapshot_map(security_codes)


def get_signal_payloads(signal_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return invalidation payloads keyed by signal id."""
    normalized_ids = [int(signal_id) for signal_id in signal_ids if str(signal_id).isdigit()]
    return get_signal_invalidation_payloads(normalized_ids)


def build_recommendation_risk_checks(recommendation, market_price: Decimal | None) -> dict[str, Any]:
    """Build risk checks for a legacy or unified recommendation."""
    result: dict[str, Any] = {}
    side = getattr(recommendation, "side", "")
    is_buy = side == "BUY" or (hasattr(recommendation, "is_buy") and recommendation.is_buy)
    is_sell = side == "SELL" or (hasattr(recommendation, "is_sell") and recommendation.is_sell)

    if market_price is None:
        result["price_validation"] = {"passed": True, "reason": "未提供市场价"}
    elif is_buy:
        passed = market_price <= recommendation.entry_price_high
        result["price_validation"] = {
            "passed": passed,
            "reason": "" if passed else f"市场价格 {market_price} 高于入场上限 {recommendation.entry_price_high}",
        }
    elif is_sell:
        passed = market_price >= recommendation.target_price_low
        result["price_validation"] = {
            "passed": passed,
            "reason": "" if passed else f"市场价格 {market_price} 低于目标下限 {recommendation.target_price_low}",
        }
    else:
        result["price_validation"] = {"passed": True, "reason": "HOLD 无价格限制"}

    if hasattr(recommendation, "beta_gate_passed"):
        result["beta_gate"] = {
            "passed": recommendation.beta_gate_passed,
            "reason": "" if recommendation.beta_gate_passed else "Beta Gate 未通过",
        }

    try:
        quota = QuotaRepository().get_quota(QuotaPeriod.WEEKLY)
        quota_ok = bool(quota and not quota.is_quota_exceeded)
        result["quota"] = {
            "passed": quota_ok,
            "remaining": quota.remaining_decisions if quota else 0,
            "reason": "" if quota_ok else "周配额不足",
        }
    except Exception as exc:
        result["quota"] = {"passed": True, "reason": f"quota check skipped: {exc}"}

    try:
        cooldown = CooldownRepository().get_active_cooldown(recommendation.security_code)
        cooldown_ok = not cooldown or cooldown.is_decision_ready
        result["cooldown"] = {
            "passed": cooldown_ok,
            "hours_remaining": cooldown.decision_ready_in_hours if cooldown else 0,
            "reason": "" if cooldown_ok else f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时",
        }
    except Exception as exc:
        result["cooldown"] = {"passed": True, "reason": f"cooldown check skipped: {exc}"}

    return result


def build_plan_risk_checks(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    """Build risk checks for a transition plan."""
    risk_checks: dict[str, Any] = {
        "plan_validation": {
            "passed": plan.can_enter_approval,
            "reason": "" if plan.can_enter_approval else "；".join(plan.blocking_issues),
        }
    }

    try:
        quota = QuotaRepository().get_quota(QuotaPeriod.WEEKLY)
        quota_ok = bool(quota and not quota.is_quota_exceeded)
        risk_checks["quota"] = {
            "passed": quota_ok,
            "remaining": quota.remaining_decisions if quota else 0,
            "reason": "" if quota_ok else "周配额不足",
        }
    except Exception as exc:
        risk_checks["quota"] = {"passed": True, "reason": f"quota check skipped: {exc}"}

    cooldown_failures: list[str] = []
    cooldown_repo = CooldownRepository()
    for order in plan.orders:
        if order.action == "HOLD":
            continue
        try:
            cooldown = cooldown_repo.get_active_cooldown(order.security_code)
            if cooldown and not cooldown.is_decision_ready:
                cooldown_failures.append(
                    f"{order.security_code}: 剩余 {cooldown.decision_ready_in_hours:.1f} 小时"
                )
        except Exception:
            continue

    risk_checks["cooldown"] = {
        "passed": not cooldown_failures,
        "reason": "" if not cooldown_failures else "；".join(cooldown_failures),
    }
    return risk_checks


def build_transition_plan_for_account(
    account_id: str,
    recommendation_ids: list[str] | None = None,
    *,
    persist: bool = True,
) -> PortfolioTransitionPlan:
    """Generate a transition plan for the selected account."""
    recommendation_repo = UnifiedRecommendationRepository()
    recommendations = recommendation_repo.get_plan_candidates(
        account_id=account_id,
        recommendation_ids=recommendation_ids,
    )
    if not recommendations:
        raise ValueError("当前账户没有可生成交易计划的已采纳推荐")

    signal_ids = sorted(
        {
            str(signal_id)
            for recommendation in recommendations
            for signal_id in (recommendation.source_signal_ids or [])
            if signal_id
        }
    )
    signal_payloads = get_signal_payloads(signal_ids)
    current_positions = get_position_snapshots(account_id=account_id)

    plan = create_portfolio_transition_plan(
        account_id=account_id,
        recommendations=recommendations,
        current_positions=current_positions,
        signal_payloads=signal_payloads,
    )
    if persist:
        plan = PortfolioTransitionPlanRepository().save(plan)
    return plan


def get_transition_plan(plan_id: str) -> PortfolioTransitionPlan | None:
    """Fetch a transition plan by id."""
    return PortfolioTransitionPlanRepository().get_by_id(plan_id)


def save_transition_plan(plan: PortfolioTransitionPlan) -> PortfolioTransitionPlan:
    """Persist a transition plan."""
    return PortfolioTransitionPlanRepository().save(plan)


def serialize_transition_plan_payload(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    """Serialize a transition plan and attach display names for UI payloads."""
    payload = plan.to_dict()
    security_codes = [
        str(item.get("asset_code") or "").upper()
        for item in payload.get("current_positions", [])
        if item.get("asset_code")
    ]
    security_codes.extend(
        [
            str(item.get("security_code") or "").upper()
            for item in payload.get("target_positions", [])
            if item.get("security_code")
        ]
    )
    security_codes.extend(
        [
            str(item.get("security_code") or "").upper()
            for item in payload.get("orders", [])
            if item.get("security_code")
        ]
    )
    security_name_map = _resolve_security_name_map(security_codes)

    for position in payload.get("current_positions", []):
        asset_code = str(position.get("asset_code") or "").upper()
        if not position.get("asset_name") and asset_code:
            position["asset_name"] = security_name_map.get(asset_code, asset_code)
        if asset_code:
            position["security_name"] = position.get("asset_name") or security_name_map.get(asset_code, asset_code)

    for position in payload.get("target_positions", []):
        security_code = str(position.get("security_code") or "").upper()
        if security_code:
            position["security_name"] = security_name_map.get(security_code, security_code)

    for order in payload.get("orders", []):
        security_code = str(order.get("security_code") or "").upper()
        if security_code:
            order["security_name"] = security_name_map.get(security_code, security_code)

    return payload


def create_plan_approval(
    plan: PortfolioTransitionPlan,
    *,
    account_id: str,
    risk_checks: dict[str, Any],
    regime_source: str,
    market_price: Decimal | None,
):
    """Create an approval request for a transition plan."""
    return ExecutionApprovalRequestRepository().create_for_transition_plan(
        plan,
        account_id=account_id,
        risk_checks=risk_checks,
        regime_source=regime_source,
        market_price=market_price,
    )


def create_unified_approval(
    recommendation,
    *,
    account_id: str,
    risk_checks: dict[str, Any],
    regime_source: str,
    market_price: Decimal | None,
):
    """Create an approval request for a unified recommendation."""
    return ExecutionApprovalRequestRepository().create_for_unified_recommendation(
        recommendation,
        account_id=account_id,
        risk_checks=risk_checks,
        regime_source=regime_source,
        market_price=market_price,
    )


def create_legacy_approval(
    recommendation,
    *,
    account_id: str,
    risk_checks: dict[str, Any],
    regime_source: str,
    market_price: Decimal | None,
):
    """Create an approval request for a legacy recommendation."""
    approval_request = create_execution_approval_request(
        recommendation=recommendation,
        account_id=account_id,
        risk_check_results=risk_checks,
        regime_source=regime_source,
        market_price_at_review=market_price,
    )
    return ExecutionApprovalRequestRepository().save(approval_request)


def has_pending_request(account_id: str, security_code: str, side: str) -> bool:
    """Check whether a pending approval already exists."""
    return ExecutionApprovalRequestRepository().has_pending_request(account_id, security_code, side)


def get_approval_request(request_id: str):
    """Fetch an approval request by id."""
    return ExecutionApprovalRequestRepository().get_by_id(request_id)


def update_approval_request_status(
    *,
    request_id: str,
    approval_status: ApprovalStatus,
    reviewer_comments: str | None = None,
):
    """Update approval status and return the latest request."""
    return ExecutionApprovalRequestRepository().update_status(
        request_id=request_id,
        approval_status=approval_status,
        reviewer_comments=reviewer_comments,
    )


def get_related_candidate_ids(request_id: str) -> list[str]:
    """Return candidate ids associated with an approval request."""
    return ExecutionApprovalRequestRepository().get_related_candidate_ids(request_id)


def get_valuation_snapshot(snapshot_id: str):
    """Fetch valuation snapshot by id."""
    return ValuationSnapshotRepository().get_by_id(snapshot_id)


def recalculate_valuation_snapshot(
    *,
    security_code: str,
    valuation_method: str,
    fair_value: Decimal,
    current_price: Decimal,
    input_parameters: dict[str, Any],
):
    """Recalculate and persist a valuation snapshot."""
    snapshot = ValuationSnapshotService().create_snapshot(
        security_code=security_code,
        valuation_method=valuation_method,
        fair_value=fair_value,
        current_price=current_price,
        input_parameters=input_parameters,
    )
    return ValuationSnapshotRepository().save(snapshot)


def get_aggregated_workspace_payload(account_id: str | None) -> dict[str, Any]:
    """Return aggregated legacy workspace recommendations."""
    recommendations = InvestmentRecommendationRepository().get_active_recommendations()
    if account_id:
        recommendations = [
            rec for rec in recommendations if getattr(rec, "account_id", "default") == account_id
        ]

    consolidated = RecommendationConsolidationService().consolidate(
        recommendations=recommendations,
        account_id=account_id or "default",
    )
    payload = []
    for rec in consolidated:
        payload.append(
            {
                "aggregation_key": f"{getattr(rec, 'account_id', account_id or 'default')}:{rec.security_code}:{rec.side}",
                "security_code": rec.security_code,
                "side": rec.side,
                "confidence": rec.confidence,
                "valuation_snapshot_id": rec.valuation_snapshot_id,
                "price_range": {
                    "entry_low": str(rec.entry_price_low),
                    "entry_high": str(rec.entry_price_high),
                    "target_low": str(rec.target_price_low),
                    "target_high": str(rec.target_price_high),
                    "stop_loss": str(rec.stop_loss_price),
                },
                "position_suggestion": {
                    "suggested_pct": rec.position_size_pct,
                    "suggested_quantity": rec.suggested_quantity,
                    "max_capital": str(rec.max_capital),
                },
                "reason_codes": rec.reason_codes,
                "human_readable_rationale": rec.human_readable_rationale,
                "source_recommendation_ids": rec.source_recommendation_ids,
            }
        )
    return payload


def get_unified_recommendation(
    recommendation_id: str,
    *,
    account_id: str | None = None,
):
    """Fetch a unified recommendation."""
    return UnifiedRecommendationRepository().get_by_recommendation_id(
        recommendation_id,
        account_id=account_id,
    )


def get_legacy_recommendation(recommendation_id: str):
    """Fetch a legacy investment recommendation."""
    return InvestmentRecommendationRepository().get_by_id(recommendation_id)


def list_workspace_recommendations(
    *,
    account_id: str,
    status: str | None,
    user_action: str | None,
    security_code: str | None,
    include_ignored: bool,
    recommendation_id: str | None,
    page: int,
    page_size: int,
    ) -> tuple[list[UnifiedRecommendationDTO], int]:
    """Return DTOs for workspace recommendations and the total count."""
    recommendations, total_count = UnifiedRecommendationRepository().list_for_workspace(
        account_id=account_id,
        status=status,
        user_action=user_action,
        security_code=security_code,
        include_ignored=include_ignored,
        recommendation_id=recommendation_id,
        page=page,
        page_size=page_size,
    )
    security_name_map = _resolve_security_name_map([rec.security_code for rec in recommendations])
    valuation_repair_map = get_valuation_repair_map([rec.security_code for rec in recommendations])
    dtos: list[UnifiedRecommendationDTO] = []
    for recommendation in recommendations:
        dto = UnifiedRecommendationDTO.from_domain(recommendation)
        _attach_security_name(dto, security_name_map)
        dto.valuation_repair = valuation_repair_map.get((recommendation.security_code or "").upper())
        dtos.append(dto)
    return dtos, total_count


def update_workspace_recommendation_action(
    *,
    recommendation_id: str,
    action: UserDecisionAction,
    note: str,
    account_id: str | None,
) -> UnifiedRecommendationDTO | None:
    """Update recommendation user action and return DTO."""
    recommendation = UnifiedRecommendationRepository().update_user_action(
        recommendation_id=recommendation_id,
        user_action=action,
        note=note,
        account_id=account_id,
    )
    if recommendation is None:
        return None
    if action == UserDecisionAction.IGNORED:
        _cancel_recommendation_sources(recommendation)
    dto = UnifiedRecommendationDTO.from_domain(recommendation)
    _attach_security_name(dto, _resolve_security_name_map([recommendation.security_code]))
    dto.valuation_repair = get_valuation_repair_map([recommendation.security_code]).get(
        (recommendation.security_code or "").upper()
    )
    return dto


def _cancel_recommendation_sources(recommendation) -> None:
    """Cancel source candidates/triggers so ignored ideas stop reappearing in workflow."""
    candidate_ids = list(getattr(recommendation, "source_candidate_ids", []) or [])
    if not candidate_ids:
        return

    try:
        from apps.alpha_trigger.domain.entities import CandidateStatus
        from apps.alpha_trigger.infrastructure.repositories import (
            get_candidate_repository,
            get_trigger_repository,
        )

        candidate_repo = get_candidate_repository()
        trigger_repo = get_trigger_repository()
    except Exception as exc:
        logger.warning("Failed to prepare alpha-trigger suppression for ignored recommendation: %s", exc)
        return

    for candidate_id in candidate_ids:
        try:
            candidate = candidate_repo.get_by_id(candidate_id)
            if candidate is None:
                continue

            if getattr(candidate, "status", None) != CandidateStatus.CANCELLED:
                candidate_repo.update_status(candidate_id, CandidateStatus.CANCELLED)

            trigger_id = str(getattr(candidate, "trigger_id", "") or "").strip()
            if trigger_id:
                trigger_repo.delete(trigger_id)
        except Exception as exc:
            logger.warning(
                "Failed to suppress ignored recommendation source %s for %s: %s",
                candidate_id,
                getattr(recommendation, "recommendation_id", ""),
                exc,
            )


def refresh_workspace_recommendations(dto: RefreshRecommendationsRequestDTO) -> RefreshRecommendationsResponseDTO:
    """Trigger workspace recommendation refresh."""
    import uuid

    task_id = f"refresh_{uuid.uuid4().hex[:12]}"
    feature_provider = create_feature_provider()
    valuation_provider = create_valuation_provider()
    signal_provider = create_signal_provider()
    candidate_provider = create_candidate_provider()
    recommendation_repo = UnifiedRecommendationRepository()
    param_repo = DecisionModelParamConfigRepository()
    param_use_case = GetModelParamsUseCase(param_repo=param_repo)
    generate_use_case = GenerateUnifiedRecommendationsUseCase(
        feature_provider=feature_provider,
        valuation_provider=valuation_provider,
        signal_provider=signal_provider,
        candidate_provider=candidate_provider,
        recommendation_repo=recommendation_repo,
        param_use_case=param_use_case,
    )
    result = generate_use_case.execute(
        GenerateRecommendationsRequest(
            account_id=dto.account_id or "default",
            security_codes=dto.security_codes,
            force_refresh=dto.force,
        )
    )
    return RefreshRecommendationsResponseDTO(
        task_id=task_id,
        status="COMPLETED" if result.success else "FAILED",
        message="刷新完成" if result.success else f"刷新失败: {result.error}",
        recommendations_count=len(result.recommendations),
        conflicts_count=len(result.conflicts),
    )


def list_workspace_conflicts(account_id: str) -> list[ConflictDTO]:
    """Return grouped workspace conflicts."""
    conflicts = UnifiedRecommendationRepository().get_conflicts(account_id)
    security_name_map = _resolve_security_name_map([rec.security_code for rec in conflicts])
    security_groups: dict[str, list[Any]] = defaultdict(list)
    for recommendation in conflicts:
        security_groups[recommendation.security_code].append(recommendation)

    results: list[ConflictDTO] = []
    for security_code, grouped in security_groups.items():
        buy_rec = None
        sell_rec = None
        for recommendation in grouped:
            dto = UnifiedRecommendationDTO.from_domain(recommendation)
            _attach_security_name(dto, security_name_map)
            if recommendation.side == "BUY":
                buy_rec = dto
            elif recommendation.side == "SELL":
                sell_rec = dto
        if buy_rec or sell_rec:
            results.append(
                ConflictDTO(
                    security_code=security_code,
                    security_name=security_name_map.get(security_code, security_code),
                    account_id=account_id,
                    buy_recommendation=buy_rec,
                    sell_recommendation=sell_rec,
                    conflict_type="BUY_SELL_CONFLICT",
                    resolution_hint="需要人工判断方向",
                )
            )
    return results


def get_model_params_payload(env: str) -> dict[str, Any]:
    """Return active model parameter payload for API responses."""
    params = {}
    for item in DecisionModelParamConfigRepository().get_active_param_details(env):
        params[item["param_key"]] = {
            "value": item["value"],
            "type": item["type"],
            "description": item["description"],
            "updated_by": item["updated_by"],
            "updated_at": item["updated_at"],
        }
    return {"env": env, "params": params}


def update_model_param_payload(
    *,
    param_key: str,
    param_value: str,
    param_type: str,
    env: str,
    updated_by: str,
    updated_reason: str,
) -> dict[str, Any]:
    """Update a model parameter and return API payload."""
    param_repo = DecisionModelParamConfigRepository()
    old_config = param_repo.get_param(param_key, env)
    old_value = old_config.param_value if old_config else ""
    response = UpdateModelParamUseCase(param_repo=param_repo).execute(
        UpdateModelParamRequest(
            param_key=param_key,
            param_value=str(param_value),
            param_type=param_type,
            env=env,
            updated_by=updated_by,
            updated_reason=updated_reason,
        )
    )
    if not response.success or response.config is None:
        raise ValueError(response.error or "更新模型参数失败")
    return {
        "param_key": response.config.param_key,
        "old_value": old_value,
        "new_value": response.config.param_value,
        "env": response.config.env,
        "version": response.config.version,
    }
