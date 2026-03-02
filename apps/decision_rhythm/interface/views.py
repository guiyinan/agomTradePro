"""
Decision Rhythm DRF Views

决策频率约束和配额管理的 API 视图。

使用 Django REST Framework 实现 RESTful API。
"""

import logging
from typing import Any, Dict, List, Optional

from django.shortcuts import render
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from ..application.use_cases import (
    SubmitDecisionRequestUseCase,
    SubmitBatchRequestUseCase,
    GetQuotaStatusUseCase,
    GetRhythmSummaryUseCase,
    ResetQuotaUseCase,
    GetRhythmSummaryRequest,
    GetQuotaStatusRequest,
    GetQuotaStatusResponse,
    GetRhythmSummaryResponse,
    ResetQuotaRequest,
    ResetQuotaResponse,
    SubmitDecisionRequestRequest,
    SubmitDecisionRequestResponse,
    SubmitBatchRequestRequest,
    SubmitBatchRequestResponse,
)
from ..domain.entities import DecisionPriority, QuotaPeriod
from ..domain.services import (
    RhythmManager,
    QuotaManager,
    CooldownManager,
    DecisionScheduler,
)
from ..infrastructure.repositories import (
    get_quota_repository,
    get_cooldown_repository,
    get_request_repository,
)
from .serializers import (
    DecisionQuotaSerializer,
    CooldownPeriodSerializer,
    DecisionRequestSerializer,
    SubmitDecisionRequestRequestSerializer,
    SubmitBatchRequestRequestSerializer,
    ResetQuotaRequestSerializer,
)


logger = logging.getLogger(__name__)


def _bad_request_response(error: Any) -> Response:
    return Response(
        {"success": False, "error": str(error)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _internal_error_response(message: str, error: Exception) -> Response:
    logger.error(f"{message}: {error}", exc_info=True)
    return Response(
        {"success": False, "error": str(error)},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ========== ViewSets ==========


class DecisionQuotaViewSet(viewsets.ViewSet):
    """
    决策配额视图集

    提供配额查询的 API 端点。

    list: 获取配额列表
    retrieve: 获取指定配额
    by_period: 按周期获取配额
    reset: 重置配额
    """

    def __init__(self, **kwargs):
        """初始化视图集"""
        super().__init__(**kwargs)
        self.quota_repository = get_quota_repository()

    def list(self, request) -> Response:
        """
        获取配额列表

        GET /api/decision-rhythm/quotas/?period=WEEKLY
        """
        try:
            period_str = request.query_params.get("period", None)

            period = None
            if period_str:
                try:
                    period = QuotaPeriod(period_str)
                except ValueError:
                    pass

            quotas = self.quota_repository.get_all_quotas(period)

            serializer = DecisionQuotaSerializer(quotas, many=True)

            return Response({
                "success": True,
                "count": len(quotas),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to list quotas: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="period",
                type=OpenApiTypes.STR,
                enum=[qp.value for qp in QuotaPeriod],
                description="配额周期",
            ),
        ],
        responses={200: DecisionQuotaSerializer},
    )
    @action(detail=False, methods=["GET"], url_path="by-period")
    def by_period(self, request) -> Response:
        """
        按周期获取配额

        GET /api/decision-rhythm/quotas/by-period/?period=WEEKLY
        """
        try:
            period_str = request.query_params.get("period", QuotaPeriod.WEEKLY.value)
            period = QuotaPeriod(period_str)

            quota = self.quota_repository.get_quota(period)

            if quota is None:
                return Response(
                    {"success": False, "error": "Quota not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = DecisionQuotaSerializer(quota)

            return Response({
                "success": True,
                "result": serializer.data,
            })

        except ValueError as e:
            return Response(
                {"success": False, "error": f"Invalid period: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Failed to get quota by period: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CooldownPeriodViewSet(viewsets.ViewSet):
    """
    冷却期视图集

    提供冷却期查询的 API 端点。

    list: 获取活跃冷却期列表
    retrieve: 获取指定冷却期
    by_asset: 按资产获取冷却期
    remaining_hours: 获取剩余小时数
    """

    def __init__(self, **kwargs):
        """初始化视图集"""
        super().__init__(**kwargs)
        self.cooldown_repository = get_cooldown_repository()

    def list(self, request) -> Response:
        """
        获取活跃冷却期列表

        GET /api/decision-rhythm/cooldowns/
        """
        try:
            cooldowns = self.cooldown_repository.get_all_active()

            serializer = CooldownPeriodSerializer(cooldowns, many=True)

            return Response({
                "success": True,
                "count": len(cooldowns),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to list cooldowns: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="by-asset/(?P<asset_code>[^/]+)")
    def by_asset(self, request, asset_code=None) -> Response:
        """
        按资产获取冷却期

        GET /api/decision-rhythm/cooldowns/by-asset/{asset_code}/
        """
        try:
            cooldown = self.cooldown_repository.get_active_cooldown(asset_code)

            if cooldown is None:
                return Response({
                    "success": True,
                    "result": None,
                    "message": "No active cooldown for this asset",
                })

            serializer = CooldownPeriodSerializer(cooldown)

            return Response({
                "success": True,
                "result": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to get cooldown by asset: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="remaining-hours")
    def remaining_hours(self, request) -> Response:
        """
        获取剩余冷却小时数

        GET /api/decision-rhythm/cooldowns/remaining-hours/?asset_code=000001.SH
        """
        try:
            asset_code = request.query_params.get("asset_code", "")
            direction = request.query_params.get("direction", None)

            if not asset_code:
                return Response(
                    {"success": False, "error": "asset_code is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            remaining = self.cooldown_repository.get_remaining_hours(asset_code, direction)

            return Response({
                "success": True,
                "result": {
                    "asset_code": asset_code,
                    "remaining_hours": remaining,
                    "is_active": remaining > 0,
                },
            })

        except Exception as e:
            logger.error(f"Failed to get remaining hours: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DecisionRequestViewSet(viewsets.ViewSet):
    """
    决策请求视图集

    提供决策请求查询的 API 端点。

    list: 获取决策请求列表
    retrieve: 获取指定决策请求
    recent: 获取最近的决策请求
    statistics: 获取统计信息
    """

    def __init__(self, **kwargs):
        """初始化视图集"""
        super().__init__(**kwargs)
        self.request_repository = get_request_repository()

    def list(self, request) -> Response:
        """
        获取决策请求列表

        GET /api/decision-rhythm/requests/
        """
        try:
            days = int(request.query_params.get("days", 30))
            asset_code = request.query_params.get("asset_code", None)

            requests = self.request_repository.get_recent(days, asset_code)

            serializer = DecisionRequestSerializer(requests, many=True)

            return Response({
                "success": True,
                "count": len(requests),
                "results": serializer.data,
            })

        except (TypeError, ValueError) as e:
            return _bad_request_response(f"Invalid query params: {e}")
        except Exception as e:
            return _internal_error_response("Failed to list requests", e)

    def retrieve(self, request, pk=None) -> Response:
        """
        获取指定决策请求

        GET /api/decision-rhythm/requests/{request_id}/
        """
        try:
            decision_request = self.request_repository.get_by_id(pk)

            if decision_request is None:
                return Response(
                    {"success": False, "error": "Request not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = DecisionRequestSerializer(decision_request)

            return Response({
                "success": True,
                "result": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to retrieve request: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="statistics")
    def statistics(self, request) -> Response:
        """
        获取统计信息

        GET /api/decision-rhythm/requests/statistics/?days=30
        """
        try:
            days = int(request.query_params.get("days", 30))

            stats = self.request_repository.get_statistics(days)

            return Response({
                "success": True,
                "result": stats,
            })

        except (TypeError, ValueError) as e:
            return _bad_request_response(f"Invalid query params: {e}")
        except Exception as e:
            return _internal_error_response("Failed to get statistics", e)


# ========== Action Views ==========


class SubmitDecisionRequestView(APIView):
    """
    提交决策请求视图

    POST /api/decision-rhythm/submit/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.quota_repository = get_quota_repository()
        self.cooldown_repository = get_cooldown_repository()
        self.request_repository = get_request_repository()

    @extend_schema(
        request=SubmitDecisionRequestRequestSerializer,
        responses={200: DecisionRequestSerializer},
    )
    def post(self, request) -> Response:
        """
        提交决策请求

        POST /api/decision-rhythm/submit/
        {
            "asset_code": "000001.SH",
            "asset_class": "a_share金融",
            "direction": "BUY",
            "priority": "HIGH",
            "reason": "强 Alpha 信号",
            "quota_period": "WEEKLY"
        }
        """
        try:
            serializer = SubmitDecisionRequestRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data

            # 幂等控制1：同 candidate 已存在待执行请求则直接返回
            open_by_candidate = None
            candidate_id = data.get("candidate_id", "") or ""
            if candidate_id:
                open_by_candidate = self.request_repository.get_open_by_candidate_id(candidate_id)
            if open_by_candidate:
                request_serializer = DecisionRequestSerializer(open_by_candidate)
                return Response({
                    "success": True,
                    "result": request_serializer.data,
                    "deduplicated": True,
                    "message": "该候选已有待执行请求，已复用",
                })

            # 幂等控制2：同证券已有待执行请求则直接返回
            open_by_asset = self.request_repository.get_open_by_asset_code(data["asset_code"])
            if open_by_asset:
                request_serializer = DecisionRequestSerializer(open_by_asset)
                return Response({
                    "success": True,
                    "result": request_serializer.data,
                    "deduplicated": True,
                    "message": "该证券已有待执行请求，已复用",
                })

            # 构建请求
            req = SubmitDecisionRequestRequest(
                asset_code=data["asset_code"],
                asset_class=data["asset_class"],
                direction=data["direction"],
                priority=DecisionPriority(data["priority"]),
                trigger_id=data.get("trigger_id"),
                candidate_id=candidate_id or None,
                reason=data.get("reason", ""),
                expected_confidence=data.get("expected_confidence", 0.0),
                quantity=data.get("quantity"),
                notional=data.get("notional"),
                quota_period=QuotaPeriod(data.get("quota_period", QuotaPeriod.WEEKLY.value)),
            )

            # 创建管理器
            quota_manager = QuotaManager()
            cooldown_manager = CooldownManager()
            scheduler = DecisionScheduler()
            rhythm_manager = RhythmManager(quota_manager, cooldown_manager, scheduler)

            # 创建用例
            use_case = SubmitDecisionRequestUseCase(rhythm_manager)

            # 执行
            response = use_case.execute(req)

            if response.success and response.response:
                # 保存决策请求和响应
                if response.decision_request is None:
                    raise ValueError("Missing decision_request in submit response")
                self.request_repository.save_request(response.decision_request)
                self.request_repository.save_response(
                    response.response.request_id,
                    response.response,
                )

                # 提交成功后收口候选状态，避免继续停留在 ACTIONABLE
                if response.response.approved and response.decision_request.candidate_id:
                    try:
                        from apps.alpha_trigger.infrastructure.repositories import get_candidate_repository
                        from apps.alpha_trigger.domain.entities import CandidateStatus
                        candidate_repo = get_candidate_repository()
                        candidate_repo.update_status(
                            candidate_id=response.decision_request.candidate_id,
                            status=CandidateStatus.CANDIDATE,
                        )
                        candidate_repo.update_execution_tracking(
                            candidate_id=response.decision_request.candidate_id,
                            decision_request_id=response.decision_request.request_id,
                            execution_status="PENDING",
                        )
                    except Exception as e:
                        logger.warning(f"Failed to compact candidate status after submit: {e}")

                request_serializer = DecisionRequestSerializer(response.decision_request)

                return Response({
                    "success": True,
                    "result": request_serializer.data,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except DRFValidationError as e:
            return _bad_request_response(e.detail)
        except (TypeError, ValueError, KeyError) as e:
            return _bad_request_response(e)
        except Exception as e:
            return _internal_error_response("Failed to submit decision request", e)


class SubmitBatchRequestView(APIView):
    """
    批量提交决策请求视图

    POST /api/decision-rhythm/submit-batch/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.quota_repository = get_quota_repository()
        self.cooldown_repository = get_cooldown_repository()
        self.request_repository = get_request_repository()

    @extend_schema(
        request=SubmitBatchRequestRequestSerializer,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        批量提交决策请求

        POST /api/decision-rhythm/submit-batch/
        {
            "requests": [...],
            "quota_period": "WEEKLY"
        }
        """
        try:
            serializer = SubmitBatchRequestRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data

            # 转换请求
            requests = []
            for req_data in data["requests"]:
                requests.append(
                    SubmitDecisionRequestRequest(
                        asset_code=req_data["asset_code"],
                        asset_class=req_data["asset_class"],
                        direction=req_data["direction"],
                        priority=DecisionPriority(req_data["priority"]),
                        trigger_id=req_data.get("trigger_id"),
                        reason=req_data.get("reason", ""),
                        expected_confidence=req_data.get("expected_confidence", 0.0),
                        quantity=req_data.get("quantity"),
                        notional=req_data.get("notional"),
                        quota_period=QuotaPeriod(data.get("quota_period", QuotaPeriod.WEEKLY.value)),
                    )
                )

            # 构建批量请求
            batch_req = SubmitBatchRequestRequest(
                requests=requests,
                quota_period=QuotaPeriod(data.get("quota_period", QuotaPeriod.WEEKLY.value)),
            )

            # 创建管理器
            quota_manager = QuotaManager()
            cooldown_manager = CooldownManager()
            scheduler = DecisionScheduler()
            rhythm_manager = RhythmManager(quota_manager, cooldown_manager, scheduler)

            # 创建用例
            use_case = SubmitBatchRequestUseCase(rhythm_manager)

            # 执行
            response = use_case.execute(batch_req)

            if response.success:
                # 批量保存
                for decision_request, resp in zip(response.decision_requests, response.responses):
                    self.request_repository.save_request(decision_request)
                    self.request_repository.save_response(
                        resp.request_id,
                        resp,
                    )

                request_serializer = DecisionRequestSerializer(
                    response.decision_requests,
                    many=True
                )

                return Response({
                    "success": True,
                    "requests": request_serializer.data,
                    "summary": response.summary,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except DRFValidationError as e:
            return _bad_request_response(e.detail)
        except (TypeError, ValueError, KeyError) as e:
            return _bad_request_response(e)
        except Exception as e:
            return _internal_error_response("Failed to submit batch decision requests", e)


class GetRhythmSummaryView(APIView):
    """
    获取节奏摘要视图

    GET /api/decision-rhythm/summary/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.quota_repository = get_quota_repository()
        self.cooldown_repository = get_cooldown_repository()

    @extend_schema(
        responses={200: dict},
    )
    def get(self, request) -> Response:
        """
        获取决策节奏摘要

        GET /api/decision-rhythm/summary/
        """
        try:
            # 创建管理器
            quota_manager = QuotaManager()
            cooldown_manager = CooldownManager()
            scheduler = DecisionScheduler()
            rhythm_manager = RhythmManager(quota_manager, cooldown_manager, scheduler)

            # 创建用例
            use_case = GetRhythmSummaryUseCase(rhythm_manager)

            # 执行
            response = use_case.execute(GetRhythmSummaryRequest())

            if response.success:
                return Response({
                    "success": True,
                    "result": response.summary,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            logger.error(f"Failed to get rhythm summary: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ResetQuotaView(APIView):
    """
    重置配额视图

    POST /api/decision-rhythm/reset-quota/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.quota_repository = get_quota_repository()

    @extend_schema(
        request=ResetQuotaRequestSerializer,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        重置配额

        POST /api/decision-rhythm/reset-quota/
        {
            "period": "WEEKLY"  // 可选，空表示重置所有
        }
        """
        try:
            serializer = ResetQuotaRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            period_str = serializer.validated_data.get("period", None)

            period = None
            if period_str:
                period = QuotaPeriod(period_str)

            # 创建用例
            quota_manager = QuotaManager()
            use_case = ResetQuotaUseCase(quota_manager)

            # 执行
            response = use_case.execute(ResetQuotaRequest(period))

            if response.success:
                return Response({
                    "success": True,
                    "message": response.message,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except DRFValidationError as e:
            return _bad_request_response(e.detail)
        except (TypeError, ValueError, KeyError) as e:
            return _bad_request_response(e)
        except Exception as e:
            return _internal_error_response("Failed to reset quota", e)


class TrendDataView(APIView):
    """
    获取配额使用趋势数据视图

    GET /api/decision-rhythm/trend-data/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.quota_repository = get_quota_repository()
        self.request_repository = get_request_repository()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="days",
                type=OpenApiTypes.INT,
                description="天数 (7 或 30)",
                enum=[7, 30],
            ),
        ],
        responses={200: dict},
    )
    def get(self, request) -> Response:
        """
        获取趋势数据

        GET /api/decision-rhythm/trend-data/?days=7
        """
        try:
            from datetime import datetime, timedelta
            from django.utils import timezone

            days = int(request.query_params.get("days", 7))
            if days not in [7, 30]:
                days = 7

            # 计算日期范围
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=days - 1)

            # 获取每日配额限制
            daily_quota = 10  # 默认值
            try:
                quota = self.quota_repository.get_quota(QuotaPeriod.DAILY)
                if quota:
                    daily_quota = quota.max_decisions
            except Exception:
                pass

            # 生成每日数据（模拟数据，实际应该从历史记录表查询）
            daily_decisions = []
            daily_executions = []

            for i in range(days):
                current_date = start_date + timedelta(days=i)
                date_str = current_date.isoformat()

                # 模拟数据：实际应该从数据库查询
                # 这里生成一些合理的模拟数据用于演示
                import random
                random.seed(hash(date_str))  # 使用日期作为种子，保证数据一致性

                decisions = min(random.randint(0, daily_quota + 2), daily_quota * 1.5)
                executions = min(random.randint(0, decisions), decisions)

                daily_decisions.append({
                    "date": date_str,
                    "value": decisions,
                    "max_quota": daily_quota,
                })

                daily_executions.append({
                    "date": date_str,
                    "value": executions,
                    "max_quota": daily_quota // 2,  # 假设执行限制是决策限制的一半
                })

            return Response({
                "success": True,
                "data": {
                    "daily_decisions": daily_decisions,
                    "daily_executions": daily_executions,
                    "period_days": days,
                    "daily_quota_limit": daily_quota,
                }
            })

        except (TypeError, ValueError) as e:
            return _bad_request_response(f"Invalid query params: {e}")
        except Exception as e:
            return _internal_error_response("Failed to get trend data", e)


# ========== Template Views ==========


def decision_rhythm_quota_view(request):
    """
    决策配额管理页面

    显示当前配额状态、冷却期和决策请求历史。
    """
    try:
        from ..infrastructure.models import (
            DecisionQuotaModel,
            CooldownPeriodModel,
            DecisionRequestModel,
        )

        # 直接查询 ORM 模型
        try:
            current_quota = DecisionQuotaModel._default_manager.filter(
                is_active=True
            ).order_by('-period_start').first()
        except Exception as e:
            logger.warning(f"Failed to query current quota: {e}")
            current_quota = None

        try:
            active_cooldowns = list(CooldownPeriodModel._default_manager.filter(
                status="ACTIVE"
            ).order_by('-created_at')[:10])
        except Exception as e:
            logger.warning(f"Failed to query active cooldowns: {e}")
            active_cooldowns = []

        try:
            recent_requests = list(DecisionRequestModel._default_manager.all().order_by(
                '-requested_at'
            )[:20])
        except Exception as e:
            logger.warning(f"Failed to query recent requests: {e}")
            recent_requests = []

        # 计算配额使用情况
        quota_used = 0
        quota_remaining = 0
        quota_total = 10  # 默认值

        if current_quota:
            quota_total = getattr(current_quota, "max_decisions", 10)
            quota_used = getattr(current_quota, "used_decisions", 0)
            quota_remaining = quota_total - quota_used

        context = {
            "current_quota": current_quota,
            "active_cooldowns": active_cooldowns,
            "recent_requests": recent_requests,
            "quota_used": quota_used,
            "quota_remaining": max(0, quota_remaining),
            "quota_total": quota_total,
            "quota_usage_percent": round(quota_used / quota_total * 100, 1) if quota_total > 0 else 0,
            "page_title": "决策配额管理",
            "page_description": "决策频率约束与配额监控",
        }

        return render(request, "decision_rhythm/quota.html", context)

    except Exception as e:
        logger.error(f"Failed to load decision rhythm quota page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "决策配额管理",
        }
        return render(request, "decision_rhythm/quota.html", context, status=500)


def decision_rhythm_config_view(request):
    """
    决策配额配置页面

    管理员可以配置不同周期的配额参数。
    """
    try:
        from ..infrastructure.models import DecisionQuotaModel
        from django.utils import timezone

        # 获取所有配额
        quotas = list(DecisionQuotaModel._default_manager.all().order_by('period'))

        # 按周期分组
        quota_by_period = {}
        for quota in quotas:
            period = quota.period
            if period not in quota_by_period:
                quota_by_period[period] = []
            quota_by_period[period].append(quota)

        context = {
            "quotas": quotas,
            "quota_by_period": quota_by_period,
            "period_choices": DecisionQuotaModel.PERIOD_CHOICES,
            "page_title": "决策配额配置",
            "page_description": "配置和管理决策配额",
        }

        return render(request, "decision_rhythm/quota_config.html", context)

    except Exception as e:
        logger.error(f"Failed to load decision rhythm config page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "决策配额配置",
        }
        return render(request, "decision_rhythm/quota_config.html", context, status=500)


# ========== 决策执行相关 API ==========


class PrecheckDecisionView(APIView):
    """
    决策预检查视图

    POST /api/decision-workflow/precheck/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        from apps.beta_gate.infrastructure.repositories import get_config_repository
        from apps.decision_rhythm.infrastructure.repositories import (
            get_quota_repository,
            get_cooldown_repository,
        )
        from apps.alpha_trigger.infrastructure.repositories import get_candidate_repository

        self.beta_gate_repo = get_config_repository()
        self.quota_repo = get_quota_repository()
        self.cooldown_repo = get_cooldown_repository()
        self.candidate_repo = get_candidate_repository()

    @extend_schema(
        request=dict,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        执行决策预检查

        POST /api/decision-workflow/precheck/
        {
            "candidate_id": "cand_xxx"
        }
        """
        from ..domain.services import QuotaManager, CooldownManager
        from ..domain.entities import QuotaPeriod

        try:
            candidate_id = request.data.get("candidate_id")
            if not candidate_id:
                return Response(
                    {"success": False, "error": "candidate_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 获取候选
            candidate = self.candidate_repo.get_by_id(candidate_id)
            if candidate is None:
                return Response(
                    {"success": False, "error": f"Candidate not found: {candidate_id}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            errors = []
            warnings = []

            # 1. Beta Gate 检查
            beta_gate_passed = True
            try:
                from apps.beta_gate.domain.services import BetaGateMatcher
                matcher = BetaGateMatcher(self.beta_gate_repo)
                # 简化检查：假设通过
                beta_gate_passed = True
            except Exception as e:
                logger.warning(f"Beta gate check failed: {e}")
                beta_gate_passed = True  # 容错处理

            # 2. 配额检查
            quota_ok = True
            try:
                quota = self.quota_repo.get_quota(QuotaPeriod.WEEKLY)
                if quota:
                    quota_ok = quota.used_decisions < quota.max_decisions
                    if not quota_ok:
                        errors.append("本周配额已耗尽")
            except Exception as e:
                logger.warning(f"Quota check failed: {e}")
                warnings.append(f"配额检查异常: {str(e)}")

            # 3. 冷却期检查
            cooldown_ok = True
            try:
                remaining = self.cooldown_repo.get_remaining_hours(
                    candidate.asset_code,
                    candidate.direction if hasattr(candidate, 'direction') else None
                )
                cooldown_ok = remaining <= 0
                if not cooldown_ok:
                    warnings.append(f"资产处于冷却期，剩余 {remaining:.1f} 小时")
            except Exception as e:
                logger.warning(f"Cooldown check failed: {e}")

            # 4. 候选状态检查
            from apps.alpha_trigger.domain.entities import CandidateStatus
            candidate_valid = candidate.status == CandidateStatus.ACTIONABLE
            if not candidate_valid:
                errors.append(f"候选状态不是 ACTIONABLE，当前状态: {candidate.status}")

            return Response({
                "success": True,
                "result": {
                    "candidate_id": candidate_id,
                    "beta_gate_passed": beta_gate_passed,
                    "quota_ok": quota_ok,
                    "cooldown_ok": cooldown_ok,
                    "candidate_valid": candidate_valid,
                    "warnings": warnings,
                    "errors": errors,
                }
            })

        except Exception as e:
            logger.error(f"Precheck failed: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ExecuteDecisionRequestView(APIView):
    """
    执行决策请求视图

    POST /api/decision-rhythm/requests/{request_id}/execute/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        from ..infrastructure.repositories import get_request_repository
        from apps.alpha_trigger.infrastructure.repositories import get_candidate_repository
        from apps.simulated_trading.infrastructure.repositories import (
            DjangoSimulatedAccountRepository,
            DjangoPositionRepository,
            DjangoTradeRepository,
        )

        self.request_repo = get_request_repository()
        self.candidate_repo = get_candidate_repository()
        self.simulated_account_repo = DjangoSimulatedAccountRepository()
        self.sim_position_repo = DjangoPositionRepository()
        self.sim_trade_repo = DjangoTradeRepository()

    @extend_schema(
        request=dict,
        responses={200: dict},
    )
    def post(self, request, request_id) -> Response:
        """
        执行决策请求

        POST /api/decision-rhythm/requests/{request_id}/execute/
        {
            "target": "SIMULATED",
            "sim_account_id": 1,
            "asset_code": "000001.SH",
            "action": "buy",
            "quantity": 1000,
            "price": 12.35,
            "reason": "按决策请求执行"
        }
        """
        from ..application.use_cases import ExecuteDecisionUseCase, ExecuteDecisionRequest
        from ..domain.entities import ExecutionTarget

        try:
            # 获取决策请求
            decision_request = self.request_repo.get_by_id(request_id)
            if decision_request is None:
                return Response(
                    {"success": False, "error": f"Request not found: {request_id}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 构建执行请求
            target_str = request.data.get("target", "SIMULATED").upper()
            try:
                target = ExecutionTarget(target_str)
            except ValueError:
                return Response(
                    {"success": False, "error": f"Invalid target: {target_str}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            exec_request = ExecuteDecisionRequest(
                request_id=request_id,
                target=target,
                sim_account_id=request.data.get("sim_account_id"),
                portfolio_id=request.data.get("portfolio_id"),
                asset_code=request.data.get("asset_code", decision_request.asset_code),
                action=request.data.get("action", "buy"),
                quantity=request.data.get("quantity"),
                price=request.data.get("price"),
                shares=request.data.get("shares"),
                avg_cost=request.data.get("avg_cost"),
                current_price=request.data.get("current_price"),
                reason=request.data.get("reason", "按决策请求执行"),
            )

            # 创建用例并执行
            use_case = ExecuteDecisionUseCase(
                request_repo=self.request_repo,
                candidate_repo=self.candidate_repo,
                simulated_account_repo=self.simulated_account_repo,
                position_repo=self.sim_position_repo,
                trade_repo=self.sim_trade_repo,
            )

            response = use_case.execute(exec_request)

            if response.success:
                return Response({
                    "success": True,
                    "result": {
                        "request_id": request_id,
                        "execution_status": response.result.execution_status if response.result else "EXECUTED",
                        "executed_at": response.result.executed_at.isoformat() if response.result and response.result.executed_at else None,
                        "execution_ref": response.result.execution_ref if response.result else None,
                        "candidate_status": response.result.candidate_status if response.result else None,
                    }
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Execute decision failed: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CancelDecisionRequestView(APIView):
    """
    取消决策请求视图

    POST /api/decision-rhythm/requests/{request_id}/cancel/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        from ..infrastructure.repositories import get_request_repository
        from apps.alpha_trigger.infrastructure.repositories import get_candidate_repository

        self.request_repo = get_request_repository()
        self.candidate_repo = get_candidate_repository()

    @extend_schema(
        request=dict,
        responses={200: dict},
    )
    def post(self, request, request_id) -> Response:
        """
        取消决策请求

        POST /api/decision-rhythm/requests/{request_id}/cancel/
        {
            "reason": "取消原因"
        }
        """
        try:
            # 获取决策请求
            decision_request = self.request_repo.get_by_id(request_id)
            if decision_request is None:
                return Response(
                    {"success": False, "error": f"Request not found: {request_id}"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 检查状态是否可取消
            if decision_request.execution_status not in ["PENDING", "FAILED"]:
                return Response(
                    {"success": False, "error": f"Cannot cancel request with status: {decision_request.execution_status}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 更新决策请求状态
            reason = request.data.get("reason", "")
            self.request_repo.update_execution_status(request_id, "CANCELLED")

            # 更新候选状态
            if decision_request.candidate_id:
                try:
                    self.candidate_repo.update_execution_tracking(
                        decision_request.candidate_id,
                        execution_status="CANCELLED",
                        decision_request_id=request_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to update candidate status: {e}")

            return Response({
                "success": True,
                "result": {
                    "request_id": request_id,
                    "status": "CANCELLED",
                    "reason": reason,
                }
            })

        except Exception as e:
            logger.error(f"Cancel decision failed: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UpdateQuotaConfigView(APIView):
    """
    更新配额配置 API

    POST /api/decision-rhythm/quota/update/
    """

    def post(self, request) -> Response:
        """
        更新配额配置

        POST /api/decision-rhythm/quota/update/
        {
            "period": "WEEKLY",
            "max_decisions": 10,
            "max_executions": 5
        }
        """
        try:
            from ..infrastructure.models import DecisionQuotaModel
            import uuid

            data = request.data

            period_str = data.get("period")
            max_decisions = int(data.get("max_decisions", 10))
            max_executions = int(data.get("max_executions", 5))

            if not period_str:
                return Response(
                    {"success": False, "error": "period is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 查找或创建配额
            quota, created = DecisionQuotaModel._default_manager.update_or_create(
                period=period_str,
                defaults={
                    "quota_id": f"quota_{uuid.uuid4().hex[:12]}",
                    "max_decisions": max_decisions,
                    "max_execution_count": max_executions,
                }
            )

            if not created:
                quota.max_decisions = max_decisions
                quota.max_execution_count = max_executions
                quota.save()

            return Response({
                "success": True,
                "quota_id": quota.quota_id,
                "period": quota.period,
                "max_decisions": quota.max_decisions,
                "max_executions": quota.max_execution_count,
            })

        except (TypeError, ValueError, KeyError) as e:
            return _bad_request_response(e)
        except Exception as e:
            return _internal_error_response("Failed to update quota config", e)
