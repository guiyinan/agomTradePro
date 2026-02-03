"""
Decision Rhythm DRF Views

决策频率约束和配额管理的 API 视图。

使用 Django REST Framework 实现 RESTful API。
"""

import logging
from typing import Any, Dict, List, Optional

from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
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

        except Exception as e:
            logger.error(f"Failed to list requests: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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

        except Exception as e:
            logger.error(f"Failed to get statistics: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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

            # 构建请求
            req = SubmitDecisionRequestRequest(
                asset_code=data["asset_code"],
                asset_class=data["asset_class"],
                direction=data["direction"],
                priority=DecisionPriority(data["priority"]),
                trigger_id=data.get("trigger_id"),
                reason=data.get("reason", ""),
                expected_confidence=data.get("expected_confidence", 0.0),
                quantity=data.get("quantity"),
                notional=data.get("notional"),
                quota_period=QuotaPeriod(data.get("quota_period", QuotaPeriod.WEEKLY.value)),
            )

            # 创建管理器
            quota_manager = QuotaManager(self.quota_repository)
            cooldown_manager = CooldownManager(self.cooldown_repository)
            scheduler = DecisionScheduler()
            rhythm_manager = RhythmManager(quota_manager, cooldown_manager, scheduler)

            # 创建用例
            use_case = SubmitDecisionRequestUseCase(rhythm_manager)

            # 执行
            response = use_case.execute(req)

            if response.success and response.response:
                # 保存决策请求和响应
                self.request_repository.save_request(response.response.request)
                self.request_repository.save_response(
                    response.response.request.request_id,
                    response.response,
                )

                request_serializer = DecisionRequestSerializer(response.response.request)

                return Response({
                    "success": True,
                    "result": request_serializer.data,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Failed to submit decision request: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
            quota_manager = QuotaManager(self.quota_repository)
            cooldown_manager = CooldownManager(self.cooldown_repository)
            scheduler = DecisionScheduler()
            rhythm_manager = RhythmManager(quota_manager, cooldown_manager, scheduler)

            # 创建用例
            use_case = SubmitBatchRequestUseCase(rhythm_manager)

            # 执行
            response = use_case.execute(batch_req)

            if response.success:
                # 批量保存
                for resp in response.responses:
                    self.request_repository.save_request(resp.request)
                    self.request_repository.save_response(
                        resp.request.request_id,
                        resp,
                    )

                request_serializer = DecisionRequestSerializer(
                    [r.request for r in response.responses],
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

        except Exception as e:
            logger.error(f"Failed to submit batch decision requests: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
            quota_manager = QuotaManager(self.quota_repository)
            cooldown_manager = CooldownManager(self.cooldown_repository)
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
            quota_manager = QuotaManager(self.quota_repository)
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

        except Exception as e:
            logger.error(f"Failed to reset quota: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
