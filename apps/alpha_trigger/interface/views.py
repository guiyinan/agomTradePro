"""
Alpha Trigger DRF Views

Alpha 事件触发的 API 视图。

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
    CreateAlphaTriggerUseCase,
    CheckTriggerInvalidationUseCase,
    EvaluateAlphaTriggerUseCase,
    GenerateCandidateUseCase,
    CreateTriggerRequest,
    CreateTriggerResponse,
    CheckInvalidationRequest,
    CheckInvalidationResponse,
    EvaluateTriggerRequest,
    EvaluateTriggerResponse,
    GenerateCandidateRequest,
    GenerateCandidateResponse,
)
from ..domain.entities import (
    TriggerType,
    TriggerStatus,
    SignalStrength,
    CandidateStatus,
    InvalidationType,
)
from ..domain.services import TriggerConfig
from ..infrastructure.repositories import (
    get_trigger_repository,
    get_candidate_repository,
)
from .serializers import (
    AlphaTriggerSerializer,
    AlphaCandidateSerializer,
    CreateTriggerRequestSerializer,
    CheckInvalidationRequestSerializer,
    EvaluateTriggerRequestSerializer,
    GenerateCandidateRequestSerializer,
    UpdateCandidateStatusRequestSerializer,
)


logger = logging.getLogger(__name__)


# ========== ViewSets ==========


class AlphaTriggerViewSet(viewsets.ViewSet):
    """
    Alpha 触发器视图集

    提供触发器 CRUD 操作的 API 端点。

    list: 获取触发器列表
    retrieve: 获取指定触发器
    active: 获取活跃触发器
    by_asset: 按资产获取触发器
    by_regime: 按 Regime 获取触发器
    """

    def __init__(self, **kwargs):
        """初始化视图集"""
        super().__init__(**kwargs)
        self.trigger_repository = get_trigger_repository()
        self.candidate_repository = get_candidate_repository()

    def list(self, request) -> Response:
        """
        获取触发器列表

        GET /api/alpha-triggers/triggers/
        ?asset_code=000001.SH&status=ACTIVE
        """
        try:
            asset_code = request.query_params.get("asset_code", None)
            status_str = request.query_params.get("status", None)

            if asset_code:
                triggers = self.trigger_repository.get_by_asset(asset_code)
            else:
                triggers = self.trigger_repository.get_active()

            serializer = AlphaTriggerSerializer(triggers, many=True)

            return Response({
                "success": True,
                "count": len(triggers),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to list triggers: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """
        获取指定触发器

        GET /api/alpha-triggers/triggers/{trigger_id}/
        """
        try:
            trigger = self.trigger_repository.get_by_id(pk)

            if trigger is None:
                return Response(
                    {"success": False, "error": "Trigger not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = AlphaTriggerSerializer(trigger)

            return Response({
                "success": True,
                "result": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to retrieve trigger: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="active")
    def active(self, request) -> Response:
        """
        获取活跃触发器

        GET /api/alpha-triggers/triggers/active/
        ?asset_code=000001.SH&min_strength=STRONG
        """
        try:
            asset_code = request.query_params.get("asset_code", None)
            min_strength_str = request.query_params.get("min_strength", None)

            min_strength = None
            if min_strength_str:
                try:
                    min_strength = SignalStrength(min_strength_str)
                except ValueError:
                    pass

            triggers = self.trigger_repository.get_active(asset_code, min_strength)

            serializer = AlphaTriggerSerializer(triggers, many=True)

            return Response({
                "success": True,
                "count": len(triggers),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to get active triggers: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="by-regime/(?P<regime>[^/]+)")
    def by_regime(self, request, regime=None) -> Response:
        """
        按 Regime 获取触发器

        GET /api/alpha-triggers/triggers/by-regime/{regime}/
        """
        try:
            triggers = self.trigger_repository.get_by_regime(regime)

            serializer = AlphaTriggerSerializer(triggers, many=True)

            return Response({
                "success": True,
                "count": len(triggers),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to get triggers by regime: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="statistics")
    def statistics(self, request) -> Response:
        """
        获取统计信息

        GET /api/alpha-triggers/triggers/statistics/?days=30
        """
        try:
            days = int(request.query_params.get("days", 30))

            stats = self.trigger_repository.get_statistics(days)

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


class AlphaCandidateViewSet(viewsets.ViewSet):
    """
    Alpha 候选视图集

    提供候选查询和更新的 API 端点。

    list: 获取候选列表
    retrieve: 获取指定候选
    actionable: 获取可操作候选
    watch_list: 获取观察列表
    update_status: 更新候选状态
    """

    def __init__(self, **kwargs):
        """初始化视图集"""
        super().__init__(**kwargs)
        self.candidate_repository = get_candidate_repository()

    def list(self, request) -> Response:
        """
        获取候选列表

        GET /api/alpha-triggers/candidates/
        ?asset_code=000001.SH&status=ACTIONABLE
        """
        try:
            asset_code = request.query_params.get("asset_code", None)
            status_str = request.query_params.get("status", None)

            if asset_code:
                candidate_status = None
                if status_str:
                    try:
                        candidate_status = CandidateStatus(status_str)
                    except ValueError:
                        pass
                candidates = self.candidate_repository.get_by_asset(asset_code, candidate_status)
            else:
                candidates = self.candidate_repository.get_actionable()

            serializer = AlphaCandidateSerializer(candidates, many=True)

            return Response({
                "success": True,
                "count": len(candidates),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to list candidates: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """
        获取指定候选

        GET /api/alpha-triggers/candidates/{candidate_id}/
        """
        try:
            candidate = self.candidate_repository.get_by_id(pk)

            if candidate is None:
                return Response(
                    {"success": False, "error": "Candidate not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = AlphaCandidateSerializer(candidate)

            return Response({
                "success": True,
                "result": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to retrieve candidate: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="actionable")
    def actionable(self, request) -> Response:
        """
        获取可操作候选

        GET /api/alpha-triggers/candidates/actionable/?min_strength=STRONG
        """
        try:
            min_strength_str = request.query_params.get("min_strength", None)

            min_strength = None
            if min_strength_str:
                try:
                    min_strength = SignalStrength(min_strength_str)
                except ValueError:
                    pass

            candidates = self.candidate_repository.get_actionable(min_strength)

            serializer = AlphaCandidateSerializer(candidates, many=True)

            return Response({
                "success": True,
                "count": len(candidates),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to get actionable candidates: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="watch-list")
    def watch_list(self, request) -> Response:
        """
        获取观察列表

        GET /api/alpha-triggers/candidates/watch-list/
        """
        try:
            candidates = self.candidate_repository.get_watch_list()

            serializer = AlphaCandidateSerializer(candidates, many=True)

            return Response({
                "success": True,
                "count": len(candidates),
                "results": serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to get watch list: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        request=UpdateCandidateStatusRequestSerializer,
        responses={200: AlphaCandidateSerializer},
    )
    @action(detail=True, methods=["POST"], url_path="update-status")
    def update_status(self, request, pk=None) -> Response:
        """
        更新候选状态

        POST /api/alpha-triggers/candidates/{candidate_id}/update-status/
        """
        try:
            serializer = UpdateCandidateStatusRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            status_value = serializer.validated_data["status"]
            new_status = CandidateStatus(status_value)

            candidate = self.candidate_repository.update_status(pk, new_status)

            candidate_serializer = AlphaCandidateSerializer(candidate)

            return Response({
                "success": True,
                "result": candidate_serializer.data,
            })

        except Exception as e:
            logger.error(f"Failed to update candidate status: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="statistics")
    def statistics(self, request) -> Response:
        """
        获取统计信息

        GET /api/alpha-triggers/candidates/statistics/?days=30
        """
        try:
            days = int(request.query_params.get("days", 30))

            stats = self.candidate_repository.get_statistics(days)

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


class CreateTriggerView(APIView):
    """
    创建触发器视图

    POST /api/alpha-triggers/create/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_trigger_repository()

    @extend_schema(
        request=CreateTriggerRequestSerializer,
        responses={200: AlphaTriggerSerializer},
    )
    def post(self, request) -> Response:
        """
        创建 Alpha 触发器

        POST /api/alpha-triggers/create/
        {
            "trigger_type": "MOMENTUM_SIGNAL",
            "asset_code": "000001.SH",
            "asset_class": "a_share金融",
            "direction": "LONG",
            "trigger_condition": {...},
            "invalidation_conditions": [...],
            "confidence": 0.75,
            "thesis": "..."
        }
        """
        try:
            serializer = CreateTriggerRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data

            # 转换证伪条件
            invalidation_conditions = [
                cond.to_domain()
                for cond in serializer.fields["invalidation_conditions"].to_internal_value(
                    data.get("invalidation_conditions", [])
                )
            ]

            # 构建请求
            req = CreateTriggerRequest(
                trigger_type=TriggerType(data["trigger_type"]),
                asset_code=data["asset_code"],
                asset_class=data["asset_class"],
                direction=data["direction"],
                trigger_condition=data["trigger_condition"],
                invalidation_conditions=invalidation_conditions,
                confidence=data["confidence"],
                thesis=data.get("thesis", ""),
                expires_in_days=data.get("expires_in_days"),
                related_regime=data.get("related_regime"),
                related_policy_level=data.get("related_policy_level"),
                source_signal_id=data.get("source_signal_id"),
            )

            # 创建用例
            config = TriggerConfig()
            use_case = CreateAlphaTriggerUseCase(self.trigger_repository, config)

            # 执行
            response = use_case.execute(req)

            if response.success:
                trigger_serializer = AlphaTriggerSerializer(response.trigger)

                return Response({
                    "success": True,
                    "result": trigger_serializer.data,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Failed to create trigger: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CheckInvalidationView(APIView):
    """
    检查证伪视图

    POST /api/alpha-triggers/check-invalidation/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_trigger_repository()

    @extend_schema(
        request=CheckInvalidationRequestSerializer,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        检查触发器是否被证伪

        POST /api/alpha-triggers/check-invalidation/
        {
            "trigger_id": "trigger_001",
            "current_indicator_values": {"CN_PMI_MANUFACTURING": 49.5},
            "current_regime": "Slowdown"
        }
        """
        try:
            serializer = CheckInvalidationRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data

            # 构建请求
            req = CheckInvalidationRequest(
                trigger_id=data["trigger_id"],
                current_indicator_values=data["current_indicator_values"],
                current_regime=data.get("current_regime"),
            )

            # 创建用例
            use_case = CheckTriggerInvalidationUseCase(self.trigger_repository)

            # 执行
            response = use_case.execute(req)

            if response.success:
                return Response({
                    "success": True,
                    "is_invalidated": response.is_invalidated,
                    "reason": response.reason,
                    "conditions_met": response.conditions_met,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Failed to check invalidation: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class EvaluateTriggerView(APIView):
    """
    评估触发器视图

    POST /api/alpha-triggers/evaluate/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_trigger_repository()

    @extend_schema(
        request=EvaluateTriggerRequestSerializer,
        responses={200: dict},
    )
    def post(self, request) -> Response:
        """
        评估触发器是否应该触发

        POST /api/alpha-triggers/evaluate/
        {
            "trigger_id": "trigger_001",
            "current_data": {...}
        }
        """
        try:
            serializer = EvaluateTriggerRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data

            # 构建请求
            req = EvaluateTriggerRequest(
                trigger_id=data["trigger_id"],
                current_data=data["current_data"],
            )

            # 创建用例
            config = TriggerConfig()
            use_case = EvaluateAlphaTriggerUseCase(self.trigger_repository, config)

            # 执行
            response = use_case.execute(req)

            if response.success:
                return Response({
                    "success": True,
                    "should_trigger": response.should_trigger,
                    "reason": response.reason,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Failed to evaluate trigger: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GenerateCandidateView(APIView):
    """
    生成候选视图

    POST /api/alpha-triggers/generate-candidate/
    """

    def __init__(self, **kwargs):
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_trigger_repository()
        self.candidate_repository = get_candidate_repository()

    @extend_schema(
        request=GenerateCandidateRequestSerializer,
        responses={200: AlphaCandidateSerializer},
    )
    def post(self, request) -> Response:
        """
        从触发器生成 Alpha 候选

        POST /api/alpha-triggers/generate-candidate/
        {
            "trigger_id": "trigger_001",
            "time_window_days": 90
        }
        """
        try:
            serializer = GenerateCandidateRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data

            # 构建请求
            req = GenerateCandidateRequest(
                trigger_id=data["trigger_id"],
                time_window_days=data.get("time_window_days", 90),
            )

            # 创建用例
            use_case = GenerateCandidateUseCase(
                self.trigger_repository,
                self.candidate_repository,
            )

            # 执行
            response = use_case.execute(req)

            if response.success:
                candidate_serializer = AlphaCandidateSerializer(response.candidate)

                return Response({
                    "success": True,
                    "result": candidate_serializer.data,
                })
            else:
                return Response(
                    {"success": False, "error": response.error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            logger.error(f"Failed to generate candidate: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
