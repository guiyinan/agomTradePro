"""Decision Rhythm API views for valuation pricing and execution approval workflow."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.regime.application.current_regime import resolve_current_regime

from ..domain.entities import ApprovalStatus, QuotaPeriod, create_execution_approval_request
from ..domain.services import (
    ApprovalStatusStateMachine,
    ExecutionApprovalService,
    RecommendationConsolidationService,
    ValuationSnapshotService,
)
from ..infrastructure.repositories import (
    CooldownRepository,
    ExecutionApprovalRequestRepository,
    InvestmentRecommendationRepository,
    QuotaRepository,
    ValuationSnapshotRepository,
)

logger = logging.getLogger(__name__)


def _decimal(value: Any, *, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _regime_context() -> Dict[str, Any]:
    try:
        current = resolve_current_regime() or {}
        return {
            "current_regime": current.get("regime", "UNKNOWN"),
            "confidence": current.get("confidence", 0.0),
            "source": current.get("source", "V2_CALCULATION"),
        }
    except Exception:
        return {
            "current_regime": "UNKNOWN",
            "confidence": 0.0,
            "source": "V2_CALCULATION",
        }


def _risk_checks(recommendation, market_price: Optional[Decimal]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    if market_price is None:
        result["price_validation"] = {"passed": True, "reason": "未提供市场价"}
    elif recommendation.is_buy:
        passed = market_price <= recommendation.entry_price_high
        result["price_validation"] = {
            "passed": passed,
            "reason": "" if passed else f"市场价格 {market_price} 高于入场上限 {recommendation.entry_price_high}",
        }
    elif recommendation.is_sell:
        passed = market_price >= recommendation.target_price_low
        result["price_validation"] = {
            "passed": passed,
            "reason": "" if passed else f"市场价格 {market_price} 低于目标下限 {recommendation.target_price_low}",
        }
    else:
        result["price_validation"] = {"passed": True, "reason": "HOLD 无价格限制"}

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


class ValuationSnapshotDetailView(APIView):
    """GET /api/valuation/snapshot/{snapshot_id}/"""

    def get(self, request, snapshot_id: str) -> Response:
        snapshot = ValuationSnapshotRepository().get_by_id(snapshot_id)
        if snapshot is None:
            return Response({"success": False, "error": "Valuation snapshot not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": snapshot.to_dict()})


class ValuationRecalculateView(APIView):
    """POST /api/valuation/recalculate/"""

    def post(self, request) -> Response:
        security_code = (request.data or {}).get("security_code")
        if not security_code:
            return Response({"success": False, "error": "security_code is required"}, status=status.HTTP_400_BAD_REQUEST)

        valuation_method = (request.data or {}).get("valuation_method", "COMPOSITE")
        fair_value = _decimal((request.data or {}).get("fair_value"))
        current_price = _decimal((request.data or {}).get("current_price"))
        if fair_value is None and current_price is None:
            return Response(
                {"success": False, "error": "fair_value or current_price is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fair_value = fair_value or current_price
        current_price = current_price or fair_value

        snapshot = ValuationSnapshotService().create_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=(request.data or {}).get("input_parameters") or {"source": "api_recalculate"},
        )
        snapshot = ValuationSnapshotRepository().save(snapshot)
        return Response({"success": True, "data": snapshot.to_dict()}, status=status.HTTP_201_CREATED)


class AggregatedWorkspaceView(APIView):
    """GET /api/decision/workspace/aggregated/"""

    def get(self, request) -> Response:
        repo = InvestmentRecommendationRepository()
        recommendations = repo.get_active_recommendations()

        account_id = request.query_params.get("account_id")
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

        return Response(
            {
                "success": True,
                "data": {
                    "aggregated_recommendations": payload,
                    "regime_context": _regime_context(),
                },
            }
        )


class ExecutionPreviewView(APIView):
    """POST /api/decision/execute/preview/"""

    def post(self, request) -> Response:
        recommendation_id = (request.data or {}).get("recommendation_id")
        account_id = (request.data or {}).get("account_id") or "default"
        market_price = _decimal((request.data or {}).get("market_price"))

        if not recommendation_id:
            return Response({"success": False, "error": "recommendation_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        rec_repo = InvestmentRecommendationRepository()
        recommendation = rec_repo.get_by_id(recommendation_id)
        if recommendation is None:
            return Response({"success": False, "error": "Recommendation not found"}, status=status.HTTP_404_NOT_FOUND)

        risk_checks = _risk_checks(recommendation, market_price)
        regime_source = _regime_context()["source"]

        approval_repo = ExecutionApprovalRequestRepository()
        if approval_repo.has_pending_request(account_id, recommendation.security_code, recommendation.side):
            return Response(
                {"success": False, "error": "Pending request already exists for this account/security/side"},
                status=status.HTTP_409_CONFLICT,
            )

        approval_request = create_execution_approval_request(
            recommendation=recommendation,
            account_id=account_id,
            risk_check_results=risk_checks,
            regime_source=regime_source,
            market_price_at_review=market_price,
        )
        approval_request = approval_repo.save(approval_request)

        return Response(
            {
                "success": True,
                "data": {
                    "request_id": approval_request.request_id,
                    "recommendation_id": recommendation.recommendation_id,
                    "valuation_snapshot_id": recommendation.valuation_snapshot_id,
                    "preview": {
                        "security_code": recommendation.security_code,
                        "side": recommendation.side,
                        "confidence": recommendation.confidence,
                        "fair_value": str(recommendation.fair_value),
                        "price_range": recommendation.price_range,
                        "position_suggestion": {
                            "suggested_pct": recommendation.position_size_pct,
                            "suggested_quantity": recommendation.suggested_quantity,
                            "max_capital": str(recommendation.max_capital),
                        },
                        "regime_source": regime_source,
                    },
                    "risk_checks": risk_checks,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class ExecutionApproveView(APIView):
    """POST /api/decision/execute/approve/"""

    def post(self, request) -> Response:
        request_id = (request.data or {}).get("approval_request_id")
        reviewer_comments = (request.data or {}).get("reviewer_comments", "")
        market_price = _decimal((request.data or {}).get("market_price"))

        if not request_id:
            return Response({"success": False, "error": "approval_request_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        repo = ExecutionApprovalRequestRepository()
        approval_request = repo.get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)

        can_approve, reason = ExecutionApprovalService().can_approve(
            approval_request,
            market_price or approval_request.market_price_at_review or Decimal("0"),
        )
        if not can_approve:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        updated = repo.update_status(
            request_id=request_id,
            approval_status=ApprovalStatus.APPROVED,
            reviewer_comments=reviewer_comments,
        )
        return Response({"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}})


class ExecutionRejectView(APIView):
    """POST /api/decision/execute/reject/"""

    def post(self, request) -> Response:
        request_id = (request.data or {}).get("approval_request_id")
        reviewer_comments = (request.data or {}).get("reviewer_comments", "")

        if not request_id:
            return Response({"success": False, "error": "approval_request_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        repo = ExecutionApprovalRequestRepository()
        approval_request = repo.get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)

        can_transition, reason = ApprovalStatusStateMachine.validate_transition(
            approval_request.approval_status,
            ApprovalStatus.REJECTED,
        )
        if not can_transition:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        updated = repo.update_status(
            request_id=request_id,
            approval_status=ApprovalStatus.REJECTED,
            reviewer_comments=reviewer_comments,
        )
        return Response({"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}})


class ExecutionRequestDetailView(APIView):
    """GET /api/decision/execute/{request_id}/"""

    def get(self, request, request_id: str) -> Response:
        approval_request = ExecutionApprovalRequestRepository().get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": approval_request.to_dict()})


# ============================================================================
# 统一推荐 API 端点（Top-down + Bottom-up 融合）
# ============================================================================


from ..application.dtos import (
    UnifiedRecommendationDTO,
    RefreshRecommendationsRequestDTO,
    RefreshRecommendationsResponseDTO,
    ConflictDTO,
    RecommendationsListDTO,
    ConflictsListDTO,
)
from ..application.use_cases import (
    GetModelParamsUseCase,
    GenerateUnifiedRecommendationsUseCase,
    GenerateRecommendationsRequest,
    GetUnifiedRecommendationsUseCase,
    GetRecommendationsRequest,
    GetConflictsUseCase,
    GetConflictsRequest,
)
from ..infrastructure.models import (
    UnifiedRecommendationModel,
    DecisionFeatureSnapshotModel,
    DecisionModelParamConfigModel,
)


class UnifiedRecommendationsView(APIView):
    """
    GET /api/decision/workspace/recommendations/

    返回统一聚合建议列表。
    """

    def get(self, request) -> Response:
        """
        获取推荐列表

        Query params:
            account_id: 账户 ID（必填）
            status: 状态过滤（可选）
            page: 页码（默认 1）
            page_size: 每页大小（默认 20）
        """
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        status_filter = request.query_params.get("status")
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return Response(
                {"success": False, "error": "page and page_size must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or page_size < 1 or page_size > 200:
            return Response(
                {"success": False, "error": "page must be >=1 and page_size must be in [1, 200]"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 查询数据库
            queryset = UnifiedRecommendationModel.objects.filter(account_id=account_id)

            # 排除冲突
            queryset = queryset.exclude(status="CONFLICT")

            # 状态过滤
            if status_filter:
                queryset = queryset.filter(status=status_filter)

            # 排序
            queryset = queryset.order_by("-composite_score", "-created_at")

            # 分页
            total_count = queryset.count()
            start = (page - 1) * page_size
            end = start + page_size
            models = queryset[start:end]

            # 转换为 DTO
            recommendations = []
            for model in models:
                dto = UnifiedRecommendationDTO(
                    recommendation_id=model.recommendation_id,
                    account_id=model.account_id,
                    security_code=model.security_code,
                    side=model.side,
                    regime=model.regime,
                    regime_confidence=model.regime_confidence,
                    policy_level=model.policy_level,
                    beta_gate_passed=model.beta_gate_passed,
                    sentiment_score=model.sentiment_score,
                    flow_score=model.flow_score,
                    technical_score=model.technical_score,
                    fundamental_score=model.fundamental_score,
                    alpha_model_score=model.alpha_model_score,
                    composite_score=model.composite_score,
                    confidence=model.confidence,
                    reason_codes=model.reason_codes or [],
                    human_rationale=model.human_rationale,
                    fair_value=model.fair_value,
                    entry_price_low=model.entry_price_low,
                    entry_price_high=model.entry_price_high,
                    target_price_low=model.target_price_low,
                    target_price_high=model.target_price_high,
                    stop_loss_price=model.stop_loss_price,
                    position_pct=model.position_pct,
                    suggested_quantity=model.suggested_quantity,
                    max_capital=model.max_capital,
                    source_signal_ids=model.source_signal_ids or [],
                    source_candidate_ids=model.source_candidate_ids or [],
                    feature_snapshot_id=model.feature_snapshot.snapshot_id if model.feature_snapshot else "",
                    status=model.status,
                    created_at=model.created_at,
                    updated_at=model.updated_at,
                )
                recommendations.append(dto)

            # 构建响应
            list_dto = RecommendationsListDTO(
                recommendations=recommendations,
                total_count=total_count,
                page=page,
                page_size=page_size,
            )

            return Response({
                "success": True,
                "data": list_dto.to_dict(),
            })

        except Exception as e:
            logger.error(f"Failed to get recommendations: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RefreshRecommendationsView(APIView):
    """
    POST /api/decision/workspace/recommendations/refresh/

    手动触发推荐重算。
    """

    def post(self, request) -> Response:
        """
        触发刷新

        Request body:
            account_id: 账户 ID（可选，不传则刷新所有账户）
            security_codes: 证券代码列表（可选）
            force: 是否强制刷新（默认 False）
            async_mode: 是否异步执行（默认 True）
        """
        from django.core.cache import cache
        from ..application.use_cases import (
            GenerateUnifiedRecommendationsUseCase,
            GetModelParamsUseCase,
        )
        from ..infrastructure.feature_providers import (
            create_feature_provider,
            create_valuation_provider,
            create_signal_provider,
            create_candidate_provider,
        )
        from ..infrastructure.repositories import UnifiedRecommendationRepository
        import uuid

        # 解析请求
        dto = RefreshRecommendationsRequestDTO.from_dict(request.data or {})

        try:
            # 生成任务 ID
            task_id = f"refresh_{uuid.uuid4().hex[:12]}"

            # 创建提供者和仓储
            feature_provider = create_feature_provider()
            valuation_provider = create_valuation_provider()
            signal_provider = create_signal_provider()
            candidate_provider = create_candidate_provider()
            recommendation_repo = UnifiedRecommendationRepository()

            # 创建参数用例
            param_use_case = GetModelParamsUseCase()

            # 创建生成用例
            generate_use_case = GenerateUnifiedRecommendationsUseCase(
                feature_provider=feature_provider,
                valuation_provider=valuation_provider,
                signal_provider=signal_provider,
                candidate_provider=candidate_provider,
                recommendation_repo=recommendation_repo,
                param_use_case=param_use_case,
            )

            # 执行生成
            from ..application.use_cases import GenerateRecommendationsRequest
            generate_request = GenerateRecommendationsRequest(
                account_id=dto.account_id or "default",
                security_codes=dto.security_codes,
                force_refresh=dto.force,
            )

            result = generate_use_case.execute(generate_request)

            # 构建响应
            response_dto = RefreshRecommendationsResponseDTO(
                task_id=task_id,
                status="COMPLETED" if result.success else "FAILED",
                message="刷新完成" if result.success else f"刷新失败: {result.error}",
                recommendations_count=len(result.recommendations),
                conflicts_count=len(result.conflicts),
            )

            return Response({
                "success": result.success,
                "data": response_dto.to_dict(),
            })

        except Exception as e:
            logger.error(f"Failed to refresh recommendations: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConflictsView(APIView):
    """
    GET /api/decision/workspace/conflicts/

    返回冲突建议。
    """

    def get(self, request) -> Response:
        """
        获取冲突列表

        Query params:
            account_id: 账户 ID（必填）
        """
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 查询冲突推荐
            conflicts_models = UnifiedRecommendationModel.objects.filter(
                account_id=account_id,
                status="CONFLICT",
            ).order_by("-created_at")

            # 按 security_code 分组，构建 ConflictDTO
            from collections import defaultdict
            security_groups = defaultdict(list)
            for model in conflicts_models:
                security_groups[model.security_code].append(model)

            conflicts = []
            for security_code, models in security_groups.items():
                buy_rec = None
                sell_rec = None

                for model in models:
                    dto = UnifiedRecommendationDTO(
                        recommendation_id=model.recommendation_id,
                        account_id=model.account_id,
                        security_code=model.security_code,
                        side=model.side,
                        composite_score=model.composite_score,
                        confidence=model.confidence,
                        status=model.status,
                    )

                    if model.side == "BUY":
                        buy_rec = dto
                    elif model.side == "SELL":
                        sell_rec = dto

                if buy_rec or sell_rec:
                    conflict_dto = ConflictDTO(
                        security_code=security_code,
                        account_id=account_id,
                        buy_recommendation=buy_rec,
                        sell_recommendation=sell_rec,
                        conflict_type="BUY_SELL_CONFLICT",
                        resolution_hint="需要人工判断方向",
                    )
                    conflicts.append(conflict_dto)

            # 构建响应
            list_dto = ConflictsListDTO(
                conflicts=conflicts,
                total_count=len(conflicts),
            )

            return Response({
                "success": True,
                "data": list_dto.to_dict(),
            })

        except Exception as e:
            logger.error(f"Failed to get conflicts: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ModelParamsView(APIView):
    """
    GET /api/decision/workspace/params/

    获取当前模型参数配置。
    """

    def get(self, request) -> Response:
        """
        获取参数配置

        Query params:
            env: 环境（默认 dev）
        """
        env = request.query_params.get("env", "dev")

        try:
            # 查询激活的参数
            configs = DecisionModelParamConfigModel.objects.filter(
                env=env,
                is_active=True,
            ).order_by("param_key")

            params = {}
            for config in configs:
                params[config.param_key] = {
                    "value": config.param_value,
                    "type": config.param_type,
                    "description": config.description,
                    "updated_by": config.updated_by,
                    "updated_at": config.updated_at.isoformat() if config.updated_at else None,
                }

            return Response({
                "success": True,
                "data": {
                    "env": env,
                    "params": params,
                },
            })

        except Exception as e:
            logger.error(f"Failed to get model params: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UpdateModelParamView(APIView):
    """
    POST /api/decision/workspace/params/update/

    更新模型参数。
    """

    def post(self, request) -> Response:
        """
        更新参数

        Request body:
            param_key: 参数键（必填）
            param_value: 参数值（必填）
            param_type: 参数类型（默认 float）
            env: 环境（默认 dev）
            updated_reason: 变更原因（必填）
        """
        from ..infrastructure.models import DecisionModelParamAuditLogModel

        param_key = request.data.get("param_key")
        param_value = request.data.get("param_value")
        param_type = request.data.get("param_type", "float")
        env = request.data.get("env", "dev")
        updated_reason = request.data.get("updated_reason", "")

        if not param_key or param_value is None:
            return Response(
                {"success": False, "error": "param_key and param_value are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 获取或创建配置
            config, created = DecisionModelParamConfigModel.objects.get_or_create(
                param_key=param_key,
                env=env,
                defaults={
                    "param_value": str(param_value),
                    "param_type": param_type,
                    "is_active": True,
                },
            )

            old_value = config.param_value if not created else ""

            if not created:
                # 更新配置
                config.param_value = str(param_value)
                config.param_type = param_type
                config.version += 1
                config.updated_by = request.user.username if hasattr(request, "user") and request.user.is_authenticated else "api"
                config.updated_reason = updated_reason
                config.save()

            # 创建审计日志
            DecisionModelParamAuditLogModel.objects.create(
                param_key=param_key,
                old_value=old_value,
                new_value=str(param_value),
                env=env,
                changed_by=request.user.username if hasattr(request, "user") and request.user.is_authenticated else "api",
                change_reason=updated_reason,
            )

            return Response({
                "success": True,
                "data": {
                    "param_key": param_key,
                    "old_value": old_value,
                    "new_value": str(param_value),
                    "env": env,
                },
            })

        except Exception as e:
            logger.error(f"Failed to update model param: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
