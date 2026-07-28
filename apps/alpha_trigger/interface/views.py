"""
Alpha Trigger DRF Views

Alpha 事件触发的 API 视图。

使用 Django REST Framework 实现 RESTful API。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.page_query_service import get_alpha_trigger_page_query_service
from ..application.repository_provider import (
    get_alpha_candidate_repository,
    get_alpha_trigger_repository,
)
from ..application.use_cases import (
    ChangeAlphaTriggerStatusUseCase,
    ChangeTriggerStatusRequest,
    CheckInvalidationRequest,
    CheckTriggerInvalidationUseCase,
    CreateAlphaTriggerUseCase,
    CreateTriggerRequest,
    EvaluateAlphaTriggerUseCase,
    EvaluateTriggerRequest,
    GenerateCandidateRequest,
    GenerateCandidateUseCase,
    UpdateAlphaTriggerUseCase,
    UpdateTriggerRequest,
)
from ..domain.entities import (
    CandidateStatus,
    InvalidationCondition,
    SignalStrength,
    TriggerConfig,
    TriggerStatus,
    TriggerType,
)
from .serializers import (
    AlphaCandidateSerializer,
    AlphaTriggerPerformanceQuerySerializer,
    AlphaTriggerSerializer,
    CheckInvalidationRequestSerializer,
    CreateTriggerRequestSerializer,
    EvaluateTriggerRequestSerializer,
    GenerateCandidateRequestSerializer,
    UpdateCandidateStatusRequestSerializer,
    UpdateTriggerRequestSerializer,
)

logger = logging.getLogger(__name__)

DecoratedCallable = TypeVar("DecoratedCallable", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed drf-spectacular decorator boundary."""

    def __call__(
        self,
        **kwargs: Any,
    ) -> Callable[[DecoratedCallable], DecoratedCallable]: ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


def _required_route_id(value: str | None, *, label: str) -> str:
    """Return a non-empty route identifier or raise a stable API error."""

    if value is None or not value.strip():
        raise ValidationError({label: f"{label} is required"})
    return value.strip()


def _parse_statistics_days(request: Request) -> int:
    """Parse the shared statistics window contract."""

    raw_days = request.query_params.get("days", "30")
    try:
        days = int(raw_days)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"days": "days must be an integer"}) from exc
    if not 1 <= days <= 365:
        raise ValidationError({"days": "days must be between 1 and 365"})
    return days


def _domain_invalidation_conditions(
    values: list[dict[str, Any]],
) -> list[InvalidationCondition]:
    """Convert validated nested serializer values into Domain entities."""

    return [
        InvalidationCondition(
            condition_type=value["condition_type"],
            indicator_code=value.get("indicator_code"),
            threshold=value.get("threshold"),
            direction=value.get("direction"),
            time_limit_hours=value.get("time_limit_hours"),
            custom_condition=value.get("custom_condition", {}),
        )
        for value in values
    ]


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

    def __init__(self, **kwargs: Any) -> None:
        """初始化视图集"""
        super().__init__(**kwargs)
        self.trigger_repository = get_alpha_trigger_repository()
        self.candidate_repository = get_alpha_candidate_repository()

    def list(self, request: Request) -> Response:
        """
        获取触发器列表

        GET /api/alpha-triggers/triggers/
        ?asset_code=000001.SH&status=ACTIVE
        """
        try:
            asset_code = request.query_params.get("asset_code", None)
            request.query_params.get("status", None)

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

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        """
        获取指定触发器

        GET /api/alpha-triggers/triggers/{trigger_id}/
        """
        try:
            trigger = self.trigger_repository.get_by_id(_required_route_id(pk, label="trigger_id"))

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

    @typed_extend_schema(
        request=UpdateTriggerRequestSerializer,
        responses={200: AlphaTriggerSerializer},
    )
    def partial_update(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        """Partially update one Alpha Trigger rule."""

        trigger_id = _required_route_id(pk, label="trigger_id")
        current = self.trigger_repository.get_by_id(trigger_id)
        if current is None:
            return Response(
                {"success": False, "error": "Trigger not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UpdateTriggerRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        conditions = current.invalidation_conditions
        if "invalidation_conditions" in data:
            conditions = _domain_invalidation_conditions(data["invalidation_conditions"])

        response = UpdateAlphaTriggerUseCase(
            self.trigger_repository,
            TriggerConfig(),
        ).execute(
            UpdateTriggerRequest(
                trigger_id=trigger_id,
                asset_class=data.get("asset_class", current.asset_class),
                direction=data.get("direction", current.direction),
                trigger_condition=data.get("trigger_condition", current.trigger_condition),
                invalidation_conditions=conditions,
                confidence=data.get("confidence", current.confidence),
                thesis=data.get("thesis", current.thesis),
                related_regime=data.get("related_regime", current.related_regime),
                related_policy_level=data.get(
                    "related_policy_level",
                    current.related_policy_level,
                ),
            )
        )
        if not response.success or response.trigger is None:
            return Response(
                {"success": False, "error": response.error},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "success": True,
                "result": AlphaTriggerSerializer(response.trigger).data,
            }
        )

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """Soft-cancel one Alpha Trigger while retaining its audit record."""

        return self._change_status(pk, TriggerStatus.CANCELLED)

    @action(detail=True, methods=["POST"], url_path="pause")
    def pause(self, request: Request, pk: str | None = None) -> Response:
        """Pause an active Alpha Trigger."""

        return self._change_status(pk, TriggerStatus.PAUSED)

    @action(detail=True, methods=["POST"], url_path="resume")
    def resume(self, request: Request, pk: str | None = None) -> Response:
        """Resume a paused Alpha Trigger."""

        return self._change_status(pk, TriggerStatus.ACTIVE)

    def _change_status(
        self,
        pk: str | None,
        target_status: TriggerStatus,
    ) -> Response:
        """Run one lifecycle transition and normalize its API response."""

        response = ChangeAlphaTriggerStatusUseCase(self.trigger_repository).execute(
            ChangeTriggerStatusRequest(
                trigger_id=_required_route_id(pk, label="trigger_id"),
                target_status=target_status,
            )
        )
        if not response.success or response.trigger is None:
            response_status = (
                status.HTTP_404_NOT_FOUND
                if response.error == "Trigger not found"
                else status.HTTP_400_BAD_REQUEST
            )
            return Response(
                {"success": False, "error": response.error},
                status=response_status,
            )
        return Response(
            {
                "success": True,
                "result": AlphaTriggerSerializer(response.trigger).data,
            }
        )

    @action(detail=False, methods=["GET"], url_path="active")
    def active(self, request: Request) -> Response:
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
    def by_regime(
        self,
        request: Request,
        regime: str | None = None,
    ) -> Response:
        """
        按 Regime 获取触发器

        GET /api/alpha-triggers/triggers/by-regime/{regime}/
        """
        try:
            triggers = self.trigger_repository.get_by_regime(
                _required_route_id(regime, label="regime")
            )

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
    def statistics(self, request: Request) -> Response:
        """
        获取统计信息

        GET /api/alpha-triggers/triggers/statistics/?days=30
        """
        try:
            days = _parse_statistics_days(request)

            stats = self.trigger_repository.get_statistics(days)

            return Response(
                {
                    "success": True,
                    "result": stats,
                }
            )

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
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

    def __init__(self, **kwargs: Any) -> None:
        """初始化视图集"""
        super().__init__(**kwargs)
        self.candidate_repository = get_alpha_candidate_repository()

    def list(self, request: Request) -> Response:
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

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        """
        获取指定候选

        GET /api/alpha-triggers/candidates/{candidate_id}/
        """
        try:
            candidate = self.candidate_repository.get_by_id(
                _required_route_id(pk, label="candidate_id")
            )

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
    def actionable(self, request: Request) -> Response:
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
    def watch_list(self, request: Request) -> Response:
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

    @typed_extend_schema(
        request=UpdateCandidateStatusRequestSerializer,
        responses={200: AlphaCandidateSerializer},
    )
    @action(detail=True, methods=["POST"], url_path="update-status")
    def update_status(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        """
        更新候选状态

        POST /api/alpha-triggers/candidates/{candidate_id}/update-status/
        """
        try:
            serializer = UpdateCandidateStatusRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            status_value = serializer.validated_data["status"]
            new_status = CandidateStatus(status_value)

            candidate = self.candidate_repository.update_status(
                _required_route_id(pk, label="candidate_id"),
                new_status,
            )

            candidate_serializer = AlphaCandidateSerializer(candidate)

            return Response(
                {
                    "success": True,
                    "result": candidate_serializer.data,
                }
            )

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Failed to update candidate status: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="statistics")
    def statistics(self, request: Request) -> Response:
        """
        获取统计信息

        GET /api/alpha-triggers/candidates/statistics/?days=30
        """
        try:
            days = _parse_statistics_days(request)

            stats = self.candidate_repository.get_statistics(days)

            return Response(
                {
                    "success": True,
                    "result": stats,
                }
            )

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
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

    def __init__(self, **kwargs: Any) -> None:
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_alpha_trigger_repository()

    @typed_extend_schema(
        request=CreateTriggerRequestSerializer,
        responses={200: AlphaTriggerSerializer},
    )
    def post(self, request: Request) -> Response:
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
            invalidation_conditions = _domain_invalidation_conditions(
                data.get("invalidation_conditions", [])
            )

            # 构建请求
            req = CreateTriggerRequest(
                trigger_type=TriggerType(data["trigger_type"]),
                asset_code=data["asset_code"],
                asset_class=data["asset_class"],
                direction=data["direction"],
                trigger_condition=data["trigger_condition"],
                invalidation_conditions=[
                    condition.to_dict() for condition in invalidation_conditions
                ],
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

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
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

    def __init__(self, **kwargs: Any) -> None:
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_alpha_trigger_repository()

    @typed_extend_schema(
        request=CheckInvalidationRequestSerializer,
        responses={200: dict},
    )
    def post(self, request: Request) -> Response:
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

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
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

    def __init__(self, **kwargs: Any) -> None:
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_alpha_trigger_repository()

    @typed_extend_schema(
        request=EvaluateTriggerRequestSerializer,
        responses={200: dict},
    )
    def post(self, request: Request) -> Response:
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

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
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

    def __init__(self, **kwargs: Any) -> None:
        """初始化视图"""
        super().__init__(**kwargs)
        self.trigger_repository = get_alpha_trigger_repository()
        self.candidate_repository = get_alpha_candidate_repository()

    @typed_extend_schema(
        request=GenerateCandidateRequestSerializer,
        responses={200: AlphaCandidateSerializer},
    )
    def post(self, request: Request) -> Response:
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

        except ValidationError as e:
            return Response(
                {"success": False, "error": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Failed to generate candidate: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== Template Views ==========


@login_required
def alpha_trigger_list_view(request: HttpRequest) -> HttpResponse:
    """
    Alpha 触发器列表页面

    显示所有触发器和候选的状态统计。
    """
    try:
        context = get_alpha_trigger_page_query_service().get_list_context()
        active_triggers = context["active_triggers"]
        actionable_candidates = context["actionable_list"]
        watch_list = context["watch_list"]
        candidate_list = context["candidate_list"]

        # 批量解析资产名称
        from apps.asset_analysis.application.asset_name_service import resolve_asset_names

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

        return render(request, "alpha_trigger/list.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger list page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "Alpha 触发器",
        }
        return render(request, "alpha_trigger/list.html", context, status=500)


@login_required
def alpha_trigger_create_view(request: HttpRequest) -> HttpResponse:
    """
    Alpha 触发器创建页面

    显示创建表单，支持 AI 助手辅助配置证伪条件。
    参考 `signal/manage.html` 的实现模式。
    """
    try:
        context = get_alpha_trigger_page_query_service().get_create_context()

        return render(request, "alpha_trigger/create.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger create page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "创建 Alpha 触发器",
        }
        return render(request, "alpha_trigger/create.html", context, status=500)


@login_required
def alpha_trigger_edit_view(
    request: HttpRequest,
    trigger_id: str,
) -> HttpResponse:
    """
    Alpha 触发器编辑页面

    加载现有触发器数据，支持修改。
    """
    try:
        context = get_alpha_trigger_page_query_service().get_edit_context(trigger_id)
        if context is None:
            return HttpResponseNotFound(f"Trigger not found: {trigger_id}")
        trigger = context["trigger"]

        # 解析资产名称
        from apps.asset_analysis.application.asset_name_service import resolve_asset_name

        trigger.asset_name = resolve_asset_name(trigger.asset_code)

        return render(request, "alpha_trigger/edit.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger edit page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "编辑 Alpha 触发器",
        }
        return render(request, "alpha_trigger/edit.html", context, status=500)


@login_required
def alpha_trigger_detail_view(
    request: HttpRequest,
    trigger_id: str,
) -> HttpResponse:
    """
    Alpha 触发器详情页面

    显示完整信息和相关候选。
    """
    try:
        context = get_alpha_trigger_page_query_service().get_detail_context(trigger_id)
        if context is None:
            return HttpResponseNotFound(f"Trigger not found: {trigger_id}")
        trigger = context["trigger"]
        candidates = context["candidates"]

        # 批量解析资产名称
        from apps.asset_analysis.application.asset_name_service import resolve_asset_names

        all_codes = [trigger.asset_code] + [c.asset_code for c in candidates if c.asset_code]
        asset_name_map = resolve_asset_names(all_codes)
        trigger.asset_name = asset_name_map.get(trigger.asset_code, trigger.asset_code)
        for candidate in candidates:
            candidate.asset_name = asset_name_map.get(candidate.asset_code, candidate.asset_code)

        return render(request, "alpha_trigger/detail.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha trigger detail page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "触发器详情",
        }
        return render(request, "alpha_trigger/detail.html", context, status=500)


@login_required
def alpha_trigger_invalidation_builder_view(request: HttpRequest) -> HttpResponse:
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


@login_required
def alpha_candidate_detail_view(
    request: HttpRequest,
    candidate_id: str,
) -> HttpResponse:
    """
    Alpha 候选详情页面

    显示候选的完整信息、状态历史和操作按钮。
    """
    try:
        context = get_alpha_trigger_page_query_service().get_candidate_detail_context(candidate_id)
        if context is None:
            return HttpResponseNotFound(f"Candidate not found: {candidate_id}")

        return render(request, "alpha_trigger/candidate_detail.html", context)

    except Exception as e:
        logger.error(f"Failed to load alpha candidate detail page: {e}", exc_info=True)
        context = {
            "error": str(e),
            "page_title": "候选详情",
        }
        return render(request, "alpha_trigger/candidate_detail.html", context, status=500)


@login_required
def alpha_trigger_performance_view(request: HttpRequest) -> HttpResponse:
    """
    Alpha 触发器性能追踪页面

    帮助用户评估触发器质量，包括：
    - 触发次数统计
    - 证伪率统计
    - 平均持仓时间
    - 转化为执行的比例
    """
    try:
        context = get_alpha_trigger_page_query_service().get_performance_context()

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

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """
        获取性能数据

        查询参数:
        - days: 统计天数（默认 30）
        - trigger_id: 特定触发器 ID（可选）
        """
        serializer = AlphaTriggerPerformanceQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data
        days = query["days"]
        trigger_id = query.get("trigger_id")
        try:
            performance_data = get_alpha_trigger_page_query_service().get_performance_data(
                days=days,
                trigger_id=trigger_id,
            )

            return Response(
                {
                    "success": True,
                    "data": performance_data,
                    "summary": {
                        "days": days,
                        "trigger_id": trigger_id,
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
