"""Policy event API views."""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.repository_provider import (
    get_current_policy_repository,
    get_policy_notification_service,
)
from ..application.use_cases import (
    CreatePolicyEventInput,
    CreatePolicyEventOutput,
    CreatePolicyEventUseCase,
    DeletePolicyEventUseCase,
    GetPolicyHistoryUseCase,
    GetPolicyStatusUseCase,
    PolicyHistoryOutput,
    PolicyStatusOutput,
    UpdatePolicyEventUseCase,
)
from ..domain.entities import PolicyLevel
from .serializers import (
    PolicyCreateResponseSerializer,
    PolicyEventIdentityQuerySerializer,
    PolicyEventSerializer,
    PolicyHistoryQuerySerializer,
    PolicyHistorySerializer,
    PolicyHistoryWithStatsSerializer,
    PolicyStatusQuerySerializer,
    PolicyStatusSerializer,
)

logger = logging.getLogger(__name__)
ViewMethod = TypeVar("ViewMethod", bound=Callable[..., Any])
Payload = dict[str, Any]


def typed_schema(*args: Any, **kwargs: Any) -> Callable[[ViewMethod], ViewMethod]:
    """Narrow drf-spectacular's dynamically typed decorator."""

    return cast(Callable[[ViewMethod], ViewMethod], extend_schema(*args, **kwargs))


class PolicyStatusView(APIView):
    """
    政策状态视图

    GET /api/policy/status/ - 获取当前政策状态
    """

    @typed_schema(
        tags=["Policy"],
        summary="获取当前政策状态",
        description="获取当前政策档位、响应配置和操作建议",
        parameters=[
            OpenApiParameter(
                name="as_of_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="截止日期 (YYYY-MM-DD)，默认为今天",
                required=False,
            )
        ],
        responses={200: PolicyStatusSerializer},
    )
    def get(self, request: Request) -> Response:
        """
        获取当前政策状态

        Query Parameters:
            as_of_date: 截止日期（可选）
        """
        try:
            # 获取参数
            query = PolicyStatusQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            as_of_date = cast(date | None, query.validated_data.get("as_of_date"))

            # 执行用例
            repo = get_current_policy_repository()
            use_case = GetPolicyStatusUseCase(event_store=repo)
            output: PolicyStatusOutput = use_case.execute(as_of_date)

            # 序列化响应
            response_data: Payload = {
                "current_level": output.current_level.value,
                "level_name": output.level_name,
                "is_intervention_active": output.is_intervention_active,
                "is_crisis_mode": output.is_crisis_mode,
                "recommendations": output.recommendations,
                "as_of_date": output.as_of_date.isoformat(),
                # 响应配置
                "market_action": output.response_config.market_action.value,
                "cash_adjustment": output.response_config.cash_adjustment,
                "signal_pause_hours": output.response_config.signal_pause_hours,
                "requires_manual_approval": output.response_config.requires_manual_approval,
                # 最新事件
                "latest_event": None,
            }

            if output.latest_event:
                response_data["latest_event"] = {
                    "event_date": output.latest_event.event_date.isoformat(),
                    "level": output.latest_event.level.value,
                    "title": output.latest_event.title,
                    "description": output.latest_event.description,
                    "evidence_url": output.latest_event.evidence_url,
                }

            # Return response_data directly (already formatted for JSON serialization)
            return Response(response_data, status=status.HTTP_200_OK)

        except (ValueError, ValidationError):
            return Response(
                {"error": "Invalid query parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.error(
                "Failed to get policy status: error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PolicyEventListView(APIView):
    """
    政策事件列表视图

    GET /api/policy/events/ - 获取政策事件列表
    POST /api/policy/events/ - 创建新的政策事件
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self) -> list[BasePermission]:
        """Restrict policy-event creation to staff users."""

        if self.request.method == "POST":
            return [IsAdminUser()]
        return cast(list[BasePermission], list(super().get_permissions()))

    @typed_schema(
        tags=["Policy"],
        summary="获取政策事件列表",
        description="获取指定日期范围内的政策事件",
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="起始日期 (YYYY-MM-DD)",
                required=True,
            ),
            OpenApiParameter(
                name="end_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="结束日期 (YYYY-MM-DD)",
                required=True,
            ),
            OpenApiParameter(
                name="level",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="筛选档位 (P0/P1/P2/P3)",
                required=False,
            ),
        ],
        responses={200: PolicyHistorySerializer},
    )
    def get(self, request: Request) -> Response:
        """获取政策事件列表"""
        try:
            # 获取参数
            query = PolicyHistoryQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            start_date = cast(date, query.validated_data["start_date"])
            end_date = cast(date, query.validated_data["end_date"])
            level_raw = cast(str | None, query.validated_data.get("level"))
            level = PolicyLevel(level_raw) if level_raw else None

            # 执行用例
            repo = get_current_policy_repository()
            use_case = GetPolicyHistoryUseCase(event_store=repo)
            output: PolicyHistoryOutput = use_case.execute(start_date, end_date, level)

            # 序列化响应
            events_data = [
                {
                    "event_date": e.event_date.isoformat(),
                    "level": e.level.value,
                    "title": e.title,
                    "description": e.description,
                    "evidence_url": e.evidence_url,
                }
                for e in output.events
            ]

            response_data: Payload = {
                "events": events_data,
                "total_count": output.total_count,
                "level_stats": {
                    level.value if isinstance(level, PolicyLevel) else str(level): count
                    for level, count in output.level_stats.items()
                },
                "start_date": output.start_date.isoformat(),
                "end_date": output.end_date.isoformat(),
            }

            serializer = PolicyHistoryWithStatsSerializer(instance=response_data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except (ValueError, ValidationError):
            return Response(
                {"error": "Invalid query parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.error(
                "Failed to get policy events: error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @typed_schema(
        tags=["Policy"],
        summary="创建政策事件",
        description="创建新的政策事件记录",
        request=PolicyEventSerializer,
        responses={201: PolicyCreateResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        """创建新的政策事件"""
        try:
            # 验证输入
            serializer = PolicyEventSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            # 创建输入 DTO
            input_data = CreatePolicyEventInput(
                event_date=serializer.validated_data["event_date"],
                level=serializer.validated_data["level"],
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                evidence_url=serializer.validated_data["evidence_url"],
            )

            # 执行用例
            repo = get_current_policy_repository()
            alert_service = get_policy_notification_service()

            use_case = CreatePolicyEventUseCase(event_store=repo, alert_service=alert_service)
            output: CreatePolicyEventOutput = use_case.execute(input_data)

            # 构建响应
            response_data: Payload = {
                "success": output.success,
                "event": None,
                "errors": output.errors,
                "warnings": output.warnings,
                "alert_triggered": output.alert_triggered,
            }

            if output.event:
                response_data["event"] = {
                    "event_date": output.event.event_date.isoformat(),
                    "level": output.event.level.value,
                    "title": output.event.title,
                    "description": output.event.description,
                    "evidence_url": output.event.evidence_url,
                }

            status_code = status.HTTP_201_CREATED if output.success else status.HTTP_400_BAD_REQUEST

            return Response(response_data, status=status_code)

        except ValidationError as exc:
            return Response(
                {
                    "success": False,
                    "errors": exc.detail,
                    "event": None,
                    "warnings": [],
                    "alert_triggered": False,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.error(
                "Failed to create policy event: error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {
                    "success": False,
                    "errors": ["Internal server error"],
                    "event": None,
                    "warnings": [],
                    "alert_triggered": False,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PolicyEventDetailView(APIView):
    """
    政策事件详情视图

    GET /api/policy/events/{date}/ - 获取指定日期的事件
    PUT /api/policy/events/{date}/ - 更新指定日期的事件（支持 ?event_id= 精确更新）
    DELETE /api/policy/events/{date}/ - 删除指定日期的事件（支持 ?event_id= 精确删除）
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self) -> list[BasePermission]:
        """Restrict policy-event mutations to staff users."""

        if self.request.method in {"PUT", "PATCH", "DELETE"}:
            return [IsAdminUser()]
        return cast(list[BasePermission], list(super().get_permissions()))

    @typed_schema(
        tags=["Policy"],
        summary="获取指定日期的政策事件",
        description="根据日期获取政策事件详情",
        parameters=[
            OpenApiParameter(
                name="event_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.PATH,
                description="事件日期 (YYYY-MM-DD)",
                required=True,
            )
        ],
        responses={200: PolicyEventSerializer},
    )
    def get(self, request: Request, event_date: str) -> Response:
        """获取指定日期的政策事件"""
        try:
            event_date_obj = date.fromisoformat(event_date)

            repo = get_current_policy_repository()
            event = repo.get_event_by_date(event_date_obj)

            if not event:
                return Response({"error": "Event not found"}, status=status.HTTP_404_NOT_FOUND)

            response_data = {
                "event_date": event.event_date.isoformat(),
                "level": event.level.value,
                "title": event.title,
                "description": event.description,
                "evidence_url": event.evidence_url,
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except ValueError:
            return Response({"error": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error(
                "Failed to get policy event: error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @typed_schema(
        tags=["Policy"],
        summary="更新政策事件",
        description="更新指定日期的政策事件",
        parameters=[
            OpenApiParameter(
                name="event_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="事件 ID（可选，传入后优先按 ID 精确更新）",
                required=False,
            )
        ],
        request=PolicyEventSerializer,
        responses={200: PolicyCreateResponseSerializer},
    )
    def put(self, request: Request, event_date: str) -> Response:
        """更新指定日期的政策事件"""
        try:
            event_date_obj = date.fromisoformat(event_date)
            query = PolicyEventIdentityQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            event_id = cast(int | None, query.validated_data.get("event_id"))

            # 验证输入
            serializer = PolicyEventSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            repo = get_current_policy_repository()
            alert_service = get_policy_notification_service()

            use_case = UpdatePolicyEventUseCase(event_store=repo, alert_service=alert_service)

            output = use_case.execute(
                event_date=event_date_obj,
                level=serializer.validated_data["level"],
                title=serializer.validated_data["title"],
                description=serializer.validated_data["description"],
                evidence_url=serializer.validated_data["evidence_url"],
                event_id=event_id,
            )

            response_data: Payload = {
                "success": output.success,
                "event": None,
                "errors": output.errors,
                "warnings": output.warnings,
                "alert_triggered": output.alert_triggered,
            }

            if output.event:
                response_data["event"] = {
                    "event_date": output.event.event_date.isoformat(),
                    "level": output.event.level.value,
                    "title": output.event.title,
                    "description": output.event.description,
                    "evidence_url": output.event.evidence_url,
                }

            status_code = status.HTTP_200_OK if output.success else status.HTTP_400_BAD_REQUEST

            return Response(response_data, status=status_code)

        except (ValueError, ValidationError):
            return Response(
                {"error": "Invalid request parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.error(
                "Failed to update policy event: error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @typed_schema(
        tags=["Policy"],
        summary="删除政策事件",
        description="删除指定日期的政策事件（可通过 event_id 精确删除单条）",
        parameters=[
            OpenApiParameter(
                name="event_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.PATH,
                description="事件日期 (YYYY-MM-DD)",
                required=True,
            ),
            OpenApiParameter(
                name="event_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="事件 ID（可选，传入后优先按 ID 精确删除）",
                required=False,
            ),
        ],
        responses={204: None},
    )
    def delete(self, request: Request, event_date: str) -> Response:
        """删除指定日期的政策事件"""
        try:
            event_date_obj = date.fromisoformat(event_date)
            query = PolicyEventIdentityQuerySerializer(data=request.query_params)
            query.is_valid(raise_exception=True)
            event_id = cast(int | None, query.validated_data.get("event_id"))

            repo = get_current_policy_repository()
            use_case = DeletePolicyEventUseCase(event_store=repo)

            success, message = use_case.execute(event_date=event_date_obj, event_id=event_id)

            if success:
                return Response(status=status.HTTP_204_NO_CONTENT)
            return Response({"error": message}, status=status.HTTP_404_NOT_FOUND)

        except (ValueError, ValidationError):
            return Response(
                {"error": "Invalid request parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.error(
                "Failed to delete policy event: error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            return Response(
                {"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
