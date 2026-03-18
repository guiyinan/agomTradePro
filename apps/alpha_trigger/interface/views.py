"""
Alpha Trigger DRF Views

Alpha 事件触发的 API 视图。

使用 Django REST Framework 实现 RESTful API。
"""

import logging
from typing import Any, Dict, List, Optional

from django.shortcuts import render
from django.http import Http404, HttpResponseNotFound
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

            return Response(
                {
                    "success": True,
                    "count": len(triggers),
                    "results": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "result": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "count": len(triggers),
                    "results": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "count": len(triggers),
                    "results": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "result": stats,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "count": len(candidates),
                    "results": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "result": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "count": len(candidates),
                    "results": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "count": len(candidates),
                    "results": serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "result": candidate_serializer.data,
                }
            )

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

            return Response(
                {
                    "success": True,
                    "result": stats,
                }
            )

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

                return Response(
                    {
                        "success": True,
                        "result": trigger_serializer.data,
                    }
                )
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
                return Response(
                    {
                        "success": True,
                        "is_invalidated": response.is_invalidated,
                        "reason": response.reason,
                        "conditions_met": response.conditions_met,
                    }
                )
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
                return Response(
                    {
                        "success": True,
                        "should_trigger": response.should_trigger,
                        "reason": response.reason,
                    }
                )
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

                return Response(
                    {
                        "success": True,
                        "result": candidate_serializer.data,
                    }
                )
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


# ========== Template Views ==========


def alpha_trigger_list_view(request):
    """
    Alpha 触发器列表页面

    显示所有触发器和候选的状态统计。
    """
    try:
        from ..infrastructure.models import AlphaTriggerModel, AlphaCandidateModel

        # 直接查询 ORM 模型
        try:
            active_triggers = list(
                AlphaTriggerModel._default_manager.filter(status="ACTIVE").order_by("-created_at")[
                    :10
                ]
            )
        except Exception as e:
            logger.warning(f"Failed to query active triggers: {e}")
            active_triggers = []

        try:
            actionable_candidates = list(
                AlphaCandidateModel._default_manager.filter(status="ACTIONABLE").order_by(
                    "-created_at"
                )[:10]
            )
        except Exception as e:
            logger.warning(f"Failed to query actionable candidates: {e}")
            actionable_candidates = []

        try:
            watch_list = list(
                AlphaCandidateModel._default_manager.filter(status="WATCH").order_by("-created_at")[
                    :10
                ]
            )
        except Exception as e:
            logger.warning(f"Failed to query watch list: {e}")
            watch_list = []

        try:
            candidate_list = list(
                AlphaCandidateModel._default_manager.filter(status="CANDIDATE").order_by(
                    "-created_at"
                )[:10]
            )
        except Exception as e:
            logger.warning(f"Failed to query candidate list: {e}")
            candidate_list = []

        # 统计各状态数量
        try:
            candidate_count = AlphaCandidateModel._default_manager.filter(
                status="CANDIDATE"
            ).count()
        except Exception as e:
            logger.warning(f"Failed to count candidates: {e}")
            candidate_count = 0

        trigger_stats = {
            "active_count": len(active_triggers),
            "total_count": AlphaTriggerModel._default_manager.count() if active_triggers else 0,
        }

        candidate_stats = {
            "watch_count": len(watch_list),
            "candidate_count": candidate_count,
            "actionable_count": len(actionable_candidates),
        }

        # 批量解析资产名称
        from shared.infrastructure.asset_name_resolver import resolve_asset_names

        all_codes = (
            [t.asset_code for t in active_triggers if t.asset_code]
            + [c.asset_code for c in actionable_candidates if c.asset_code]
            + [c.asset_code for c in watch_list if c.asset_code]
            + [c.asset_code for c in candidate_list if c.asset_code]
        )
        asset_name_map = resolve_asset_names(all_codes)
        for trigger in active_triggers:
            trigger.asset_name = asset_name_map.get(trigger.asset_code, trigger.asset_code)
        for candidate in actionable_candidates:
            candidate.asset_name = asset_name_map.get(candidate.asset_code, candidate.asset_code)
        for candidate in watch_list:
            candidate.asset_name = asset_name_map.get(candidate.asset_code, candidate.asset_code)
        for candidate in candidate_list:
            candidate.asset_name = asset_name_map.get(candidate.asset_code, candidate.asset_code)

        context = {
            "active_triggers": active_triggers,
            "actionable_list": actionable_candidates,
            "candidate_list": candidate_list,
            "watch_list": watch_list,
            "trigger_stats": trigger_stats,
            "candidate_stats": candidate_stats,
            "page_title": "Alpha 触发器",
            "page_description": "离散、可证伪、可行动的 Alpha 信号触发",
        }

        return render(request, "alpha_trigger/list.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger list page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "Alpha 触发器",
        }
        return render(request, "alpha_trigger/list.html", context, status=500)


def alpha_trigger_create_view(request):
    """
    Alpha 触发器创建页面

    显示创建表单，支持 AI 助手辅助配置证伪条件。
    参考 `signal/manage.html` 的实现模式。
    """
    try:
        from ..infrastructure.models import AlphaTriggerModel

        # 获取当前 Regime
        current_regime = None
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            current_regime = resolve_current_regime()
        except Exception as e:
            logger.warning(f"Failed to get current regime: {e}")

        # 获取当前 Policy
        current_policy = None
        try:
            from apps.policy.application.use_cases import GetCurrentPolicyUseCase
            from apps.policy.infrastructure.repositories import get_policy_repository

            policy_use_case = GetCurrentPolicyUseCase(get_policy_repository())
            policy_response = policy_use_case.execute()
            if policy_response.success and policy_response.policy_level:
                current_policy = policy_response.policy_level
        except Exception as e:
            logger.warning(f"Failed to get current policy: {e}")

        # 获取可用指标列表（从 macro_indicator 表）
        available_indicators = []
        try:
            from apps.macro.infrastructure.models import MacroIndicatorModel

            indicators = MacroIndicatorModel._default_manager.filter(is_active=True).values(
                "code", "name", "unit", "latest_value"
            )[:50]
            available_indicators = list(indicators)
        except Exception as e:
            logger.warning(f"Failed to query indicators: {e}")

        # 获取所有资产类别
        all_asset_classes = ["a_股票", "a_债券", "a_商品", "a_现金", "港股", "美股", "黄金", "原油"]

        # 获取触发器类型选项
        trigger_type_choices = AlphaTriggerModel.TRIGGER_TYPE_CHOICES

        context = {
            "current_regime": current_regime,
            "current_policy": current_policy,
            "available_indicators": available_indicators,
            "all_asset_classes": all_asset_classes,
            "trigger_type_choices": trigger_type_choices,
            "page_title": "创建 Alpha 触发器",
            "page_description": "配置可证伪的 Alpha 信号触发条件",
        }

        return render(request, "alpha_trigger/create.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger create page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "创建 Alpha 触发器",
        }
        return render(request, "alpha_trigger/create.html", context, status=500)


def alpha_trigger_edit_view(request, trigger_id):
    """
    Alpha 触发器编辑页面

    加载现有触发器数据，支持修改。
    """
    try:
        from ..infrastructure.models import AlphaTriggerModel
        from django.shortcuts import get_object_or_404

        trigger = get_object_or_404(AlphaTriggerModel, trigger_id=trigger_id)

        # 解析资产名称
        from shared.infrastructure.asset_name_resolver import resolve_asset_name

        trigger.asset_name = resolve_asset_name(trigger.asset_code)

        # 获取可用指标列表
        available_indicators = []
        try:
            from apps.macro.infrastructure.models import MacroIndicatorModel

            indicators = MacroIndicatorModel._default_manager.filter(is_active=True).values(
                "code", "name", "unit", "latest_value"
            )[:50]
            available_indicators = list(indicators)
        except Exception as e:
            logger.warning(f"Failed to query indicators: {e}")

        # 获取所有资产类别
        all_asset_classes = ["a_股票", "a_债券", "a_商品", "a_现金", "港股", "美股", "黄金", "原油"]

        context = {
            "trigger": trigger,
            "available_indicators": available_indicators,
            "all_asset_classes": all_asset_classes,
            "trigger_type_choices": AlphaTriggerModel.TRIGGER_TYPE_CHOICES,
            "page_title": f"编辑触发器: {trigger.trigger_id[:12]}...",
            "page_description": f"修改 {trigger.asset_code} 的触发条件",
        }

        return render(request, "alpha_trigger/edit.html", context)

    except Http404:
        return HttpResponseNotFound(f"Trigger not found: {trigger_id}")
    except Exception as e:
        logger.error(f"Failed to load alpha trigger edit page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "编辑 Alpha 触发器",
        }
        return render(request, "alpha_trigger/edit.html", context, status=500)


def alpha_trigger_detail_view(request, trigger_id):
    """
    Alpha 触发器详情页面

    显示完整信息和相关候选。
    """
    try:
        from ..infrastructure.models import AlphaTriggerModel, AlphaCandidateModel
        from django.shortcuts import get_object_or_404

        trigger = get_object_or_404(AlphaTriggerModel, trigger_id=trigger_id)

        # 获取相关候选
        candidates = list(
            AlphaCandidateModel._default_manager.filter(source_trigger_id=trigger_id).order_by(
                "-created_at"
            )[:20]
        )

        # 批量解析资产名称
        from shared.infrastructure.asset_name_resolver import resolve_asset_names

        all_codes = [trigger.asset_code] + [c.asset_code for c in candidates if c.asset_code]
        asset_name_map = resolve_asset_names(all_codes)
        trigger.asset_name = asset_name_map.get(trigger.asset_code, trigger.asset_code)
        for candidate in candidates:
            candidate.asset_name = asset_name_map.get(candidate.asset_code, candidate.asset_code)

        # 统计候选状态
        candidate_stats = {
            "total": len(candidates),
            "watch": len([c for c in candidates if c.status == "WATCH"]),
            "candidate": len([c for c in candidates if c.status == "CANDIDATE"]),
            "actionable": len([c for c in candidates if c.status == "ACTIONABLE"]),
            "executed": len([c for c in candidates if c.status == "EXECUTED"]),
        }

        context = {
            "trigger": trigger,
            "candidates": candidates,
            "candidate_stats": candidate_stats,
            "page_title": f"触发器详情: {trigger.trigger_id[:12]}...",
            "page_description": f"{trigger.asset_code} - {trigger.get_trigger_type_display()}",
        }

        return render(request, "alpha_trigger/detail.html", context)

    except Http404:
        return HttpResponseNotFound(f"Trigger not found: {trigger_id}")
    except Exception as e:
        logger.error(f"Failed to load alpha trigger detail page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "触发器详情",
        }
        return render(request, "alpha_trigger/detail.html", context, status=500)


def alpha_trigger_invalidation_builder_view(request):
    """
    证伪规则可视化构建器页面

    提供交互式界面构建复杂的证伪规则。
    """
    try:
        # 获取可用指标列表（预定义的常用指标）
        available_indicators = [
            {
                "code": "CN_PMI_MANUFACTURING",
                "name": "中国制造业PMI",
                "unit": "指数",
                "latest_value": 50.1,
            },
            {"code": "CN_CPI_YOY", "name": "中国CPI同比", "unit": "%", "latest_value": 2.1},
            {"code": "CN_PPI_YOY", "name": "中国PPI同比", "unit": "%", "latest_value": -2.8},
            {"code": "US_FED_FUNDS_RATE", "name": "美联储利率", "unit": "%", "latest_value": 5.25},
            {"code": "CN_SHIBOR_OVERNIGHT", "name": "SHIBOR隔夜", "unit": "%", "latest_value": 1.7},
            {
                "code": "CN_10Y_BOND_YIELD",
                "name": "中国10年期国债收益率",
                "unit": "%",
                "latest_value": 2.7,
            },
            {
                "code": "US_10Y_TREASURY_YIELD",
                "name": "美国10年期国债收益率",
                "unit": "%",
                "latest_value": 4.2,
            },
            {"code": "USD_CNY", "name": "美元兑人民币", "unit": "汇率", "latest_value": 7.2},
        ]

        # 默认 JSON 示例
        initial_json = {
            "logic_operator": "AND",
            "invalidation_delay_days": 0,
            "consecutive_count": 1,
            "conditions": [],
        }

        context = {
            "available_indicators": available_indicators,
            "initial_json": initial_json,
            "rules": [],
            "page_title": "证伪规则可视化构建器",
        }

        return render(request, "alpha_trigger/invalidation_builder.html", context)

    except Exception as e:
        logger.error(f"Failed to load invalidation builder page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "证伪规则构建器",
        }
        return render(request, "alpha_trigger/invalidation_builder.html", context, status=500)


def alpha_candidate_detail_view(request, candidate_id):
    """
    Alpha 候选详情页面

    显示候选的完整信息、状态历史和操作按钮。
    """
    try:
        from ..infrastructure.models import AlphaCandidateModel, AlphaTriggerModel
        from django.shortcuts import get_object_or_404

        candidate = get_object_or_404(AlphaCandidateModel, candidate_id=candidate_id)

        # 获取来源触发器
        source_trigger = None
        try:
            source_trigger = AlphaTriggerModel._default_manager.get(
                trigger_id=candidate.source_trigger_id
            )
        except AlphaTriggerModel.DoesNotExist:
            pass

        # P1-9: 获取关联的决策请求的 execution_ref
        execution_ref = None
        if candidate.last_decision_request_id:
            try:
                from apps.decision_rhythm.infrastructure.models import DecisionRequestModel

                decision_request = DecisionRequestModel._default_manager.filter(
                    request_id=candidate.last_decision_request_id
                ).first()
                if decision_request and decision_request.execution_ref:
                    execution_ref = decision_request.execution_ref
            except Exception as e:
                logger.warning(f"Failed to get execution_ref: {e}")

        # 解析证伪条件
        invalidation_conditions = []
        if candidate.invalidation_conditions:
            try:
                import json

                conditions = json.loads(candidate.invalidation_conditions)
                if isinstance(conditions, list):
                    invalidation_conditions = conditions
                elif isinstance(conditions, dict):
                    invalidation_conditions = [conditions]
            except json.JSONDecodeError:
                pass

        # 模拟状态历史 (实际应该从数据库查询)
        status_history = []
        # 添加初始状态
        status_history.append(
            {
                "status": "CREATED",
                "created_at": candidate.created_at,
                "note": f"由触发器 {candidate.source_trigger_id[:12]}... 创建",
            }
        )
        # 如果状态有变化，添加历史记录
        if candidate.status != "CREATED":
            status_history.append(
                {
                    "status": candidate.status,
                    "created_at": candidate.updated_at,
                    "note": "状态已更新",
                }
            )

        # 计算活跃天数
        from django.utils import timezone

        days_active = 0
        if candidate.created_at:
            days_active = (timezone.now() - candidate.created_at).days

        context = {
            "candidate": candidate,
            "source_trigger": source_trigger,
            "invalidation_conditions": invalidation_conditions,
            "status_history": status_history,
            "days_active": days_active,
            "execution_ref": execution_ref,  # P1-9: 添加执行引用
            "page_title": f"候选详情: {candidate.asset_code}",
        }

        return render(request, "alpha_trigger/candidate_detail.html", context)

    except Http404:
        return HttpResponseNotFound(f"Candidate not found: {candidate_id}")
    except Exception as e:
        logger.error(f"Failed to load alpha candidate detail page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "候选详情",
        }
        return render(request, "alpha_trigger/candidate_detail.html", context, status=500)


def alpha_trigger_performance_view(request):
    """
    Alpha 触发器性能追踪页面

    帮助用户评估触发器质量，包括：
    - 触发次数统计
    - 证伪率统计
    - 平均持仓时间
    - 转化为执行的比例
    """
    try:
        from ..infrastructure.models import AlphaTriggerModel, AlphaCandidateModel
        from django.db.models import Count, Q, Avg, F
        from django.utils import timezone
        from datetime import timedelta

        # 获取所有活跃触发器
        triggers = list(
            AlphaTriggerModel._default_manager.filter(status="ACTIVE").order_by("-created_at")
        )

        # 为每个触发器计算性能指标
        trigger_performance = []

        for trigger in triggers:
            # 获取相关候选
            candidates = AlphaCandidateModel._default_manager.filter(
                source_trigger_id=trigger.trigger_id
            )

            total_candidates = candidates.count()
            executed_count = candidates.filter(status="EXECUTED").count()
            invalidated_count = candidates.filter(status__in=["INVALIDATED", "EXPIRED"]).count()
            actionable_count = candidates.filter(status="ACTIONABLE").count()

            # 转化率（候选转为执行的比例）
            conversion_rate = 0
            if total_candidates > 0:
                conversion_rate = round(executed_count / total_candidates * 100, 1)

            # 证伪率（被证伪的候选比例）
            invalidation_rate = 0
            if total_candidates > 0:
                invalidation_rate = round(invalidated_count / total_candidates * 100, 1)

            # 平均置信度
            avg_confidence = candidates.aggregate(avg_conf=Avg("confidence"))["avg_conf"] or 0

            # 平均持仓时间（从创建到执行的天数）
            avg_holding_days = 0
            executed_candidates = candidates.filter(status="EXECUTED", executed_at__isnull=False)
            if executed_candidates.exists():
                days_list = []
                for c in executed_candidates:
                    if c.created_at and c.executed_at:
                        days = (c.executed_at - c.created_at).days
                        days_list.append(days)
                if days_list:
                    avg_holding_days = round(sum(days_list) / len(days_list), 1)

            # 触发器活跃天数
            days_active = 0
            if trigger.created_at:
                days_active = (timezone.now() - trigger.created_at).days

            # 触发频率（每天产生的候选数）
            trigger_frequency = 0
            if days_active > 0:
                trigger_frequency = round(total_candidates / days_active, 2)

            # 性能评分 (0-100)
            # 综合考虑：转化率 (40%), 证伪率反向 (30%), 置信度 (30%)
            performance_score = 0
            if total_candidates > 0:
                score = (
                    conversion_rate * 0.4
                    + (100 - invalidation_rate) * 0.3
                    + (avg_confidence * 100) * 0.3
                )
                performance_score = round(score, 1)

            trigger_performance.append(
                {
                    "trigger": trigger,
                    "total_candidates": total_candidates,
                    "executed_count": executed_count,
                    "invalidated_count": invalidated_count,
                    "actionable_count": actionable_count,
                    "conversion_rate": conversion_rate,
                    "invalidation_rate": invalidation_rate,
                    "avg_confidence": round(avg_confidence, 2),
                    "avg_holding_days": avg_holding_days,
                    "days_active": days_active,
                    "trigger_frequency": trigger_frequency,
                    "performance_score": performance_score,
                }
            )

        # 按性能评分排序
        trigger_performance.sort(key=lambda x: x["performance_score"], reverse=True)

        # 整体统计
        total_triggers = len(triggers)
        total_candidates = AlphaCandidateModel._default_manager.count()
        total_executed = AlphaCandidateModel._default_manager.filter(status="EXECUTED").count()
        overall_conversion_rate = 0
        if total_candidates > 0:
            overall_conversion_rate = round(total_executed / total_candidates * 100, 1)

        # 按类型分组统计
        trigger_type_stats = {}
        for perf in trigger_performance:
            trigger_type = perf["trigger"].get_trigger_type_display()
            if trigger_type not in trigger_type_stats:
                trigger_type_stats[trigger_type] = {
                    "count": 0,
                    "total_candidates": 0,
                    "total_executed": 0,
                    "avg_score": 0,
                    "scores": [],
                }
            stats = trigger_type_stats[trigger_type]
            stats["count"] += 1
            stats["total_candidates"] += perf["total_candidates"]
            stats["total_executed"] += perf["executed_count"]
            stats["scores"].append(perf["performance_score"])

        # 计算各类型平均分
        for trigger_type, stats in trigger_type_stats.items():
            if stats["scores"]:
                stats["avg_score"] = round(sum(stats["scores"]) / len(stats["scores"]), 1)
            stats["conversion_rate"] = 0
            if stats["total_candidates"] > 0:
                stats["conversion_rate"] = round(
                    stats["total_executed"] / stats["total_candidates"] * 100, 1
                )
            del stats["scores"]  # 移除临时列表

        # 获取最近 30 天的趋势数据
        thirty_days_ago = timezone.now() - timedelta(days=30)
        recent_candidates = AlphaCandidateModel._default_manager.filter(
            created_at__gte=thirty_days_ago
        ).order_by("created_at")

        # 按日期分组
        daily_stats = {}
        for candidate in recent_candidates:
            date_str = candidate.created_at.date().isoformat()
            if date_str not in daily_stats:
                daily_stats[date_str] = {"created": 0, "executed": 0, "invalidated": 0}
            daily_stats[date_str]["created"] += 1
            if candidate.status == "EXECUTED":
                daily_stats[date_str]["executed"] += 1
            elif candidate.status in ["INVALIDATED", "EXPIRED"]:
                daily_stats[date_str]["invalidated"] += 1

        # 转换为列表
        trend_data = []
        for date_str in sorted(daily_stats.keys()):
            trend_data.append(
                {
                    "date": date_str,
                    "created": daily_stats[date_str]["created"],
                    "executed": daily_stats[date_str]["executed"],
                    "invalidated": daily_stats[date_str]["invalidated"],
                }
            )

        context = {
            "trigger_performance": trigger_performance,
            "trigger_type_stats": trigger_type_stats,
            "trend_data": trend_data,
            "overall_stats": {
                "total_triggers": total_triggers,
                "total_candidates": total_candidates,
                "total_executed": total_executed,
                "conversion_rate": overall_conversion_rate,
            },
            "page_title": "触发器性能追踪",
            "page_description": "评估触发器质量和投资效果",
        }

        return render(request, "alpha_trigger/performance.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger performance page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "触发器性能追踪",
        }
        return render(request, "alpha_trigger/performance.html", context, status=500)


class TriggerPerformanceAPIView(APIView):
    """
    触发器性能数据 API

    GET /api/alpha-triggers/performance/?days=30
    """

    def get(self, request) -> Response:
        """
        获取性能数据

        查询参数:
        - days: 统计天数（默认 30）
        - trigger_id: 特定触发器 ID（可选）
        """
        try:
            from ..infrastructure.models import AlphaTriggerModel, AlphaCandidateModel
            from django.utils import timezone
            from datetime import timedelta
            import json

            days = int(request.query_params.get("days", 30))
            trigger_id = request.query_params.get("trigger_id", None)

            start_date = timezone.now() - timedelta(days=days)

            # 获取触发器列表
            if trigger_id:
                triggers = [
                    AlphaTriggerModel._default_manager.filter(trigger_id=trigger_id).first()
                ]
            else:
                triggers = list(AlphaTriggerModel._default_manager.filter(status="ACTIVE"))

            performance_data = []

            for trigger in triggers:
                if not trigger:
                    continue

                candidates = AlphaCandidateModel._default_manager.filter(
                    source_trigger_id=trigger.trigger_id, created_at__gte=start_date
                )

                total = candidates.count()
                executed = candidates.filter(status="EXECUTED").count()
                invalidated = candidates.filter(status__in=["INVALIDATED", "EXPIRED"]).count()

                performance_data.append(
                    {
                        "trigger_id": trigger.trigger_id,
                        "asset_code": trigger.asset_code,
                        "trigger_type": trigger.trigger_type,
                        "total_candidates": total,
                        "executed": executed,
                        "invalidated": invalidated,
                        "conversion_rate": round(executed / total * 100, 1) if total > 0 else 0,
                        "invalidation_rate": round(invalidated / total * 100, 1)
                        if total > 0
                        else 0,
                    }
                )

            return Response(
                {
                    "success": True,
                    "data": performance_data,
                    "summary": {
                        "days": days,
                        "total_triggers": len(performance_data),
                    },
                }
            )

        except Exception as e:
            logger.error(f"Failed to get performance data: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
