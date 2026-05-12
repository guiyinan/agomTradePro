"""
Events Interface Views

事件 API 视图定义。
"""

import logging
from typing import Any

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.application.dtos import (
    EventPublishRequestDTO,
    metrics_to_dto,
)
from apps.events.application.use_cases import (
    GetEventMetricsUseCase,
    PublishEventUseCase,
    QueryEventsUseCase,
    ReplayEventsUseCase,
)
from apps.events.domain.entities import EventType

from .serializers import (
    EventPublishRequestSerializer,
    EventQueryRequestSerializer,
    EventReplayRequestSerializer,
)

logger = logging.getLogger(__name__)


# ========== 基础视图 ==========


class BaseAPIView(APIView):
    """基础 API 视图"""

    def success_response(
        self,
        data: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> Response:
        """
        成功响应

        Args:
            data: 响应数据
            message: 响应消息

        Returns:
            Response 对象
        """
        response_data = {
            "success": True,
            "timestamp": timezone.now().isoformat(),
        }
        if data:
            response_data.update(data)
        if message:
            response_data["message"] = message

        return Response(response_data, status=status.HTTP_200_OK)

    def error_response(
        self,
        message: str,
        error_code: str | None = None,
        http_status: int = status.HTTP_400_BAD_REQUEST,
    ) -> Response:
        """
        错误响应

        Args:
            message: 错误消息
            error_code: 错误代码
            http_status: HTTP 状态码

        Returns:
            Response 对象
        """
        response_data = {
            "success": False,
            "message": message,
            "timestamp": timezone.now().isoformat(),
        }
        if error_code:
            response_data["error_code"] = error_code

        return Response(response_data, status=http_status)


# ========== 事件发布视图 ==========


class EventPublishView(BaseAPIView):
    """
    事件发布视图

    POST /api/events/publish/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        """
        发布事件

        Args:
            request: HTTP 请求

        Returns:
            HTTP 响应
        """
        # 验证请求
        serializer = EventPublishRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error_response(
                message="Invalid request data",
                error_code="INVALID_REQUEST",
            )

        data = serializer.validated_data

        try:
            # 创建用例请求
            use_case_request = EventPublishRequestDTO(
                event_type=data["event_type"],
                payload=data["payload"],
                metadata=data.get("metadata"),
                event_id=data.get("event_id"),
                occurred_at=data.get("occurred_at").isoformat() if data.get("occurred_at") else None,
                correlation_id=data.get("correlation_id"),
                causation_id=data.get("causation_id"),
            )

            # 执行用例
            use_case = PublishEventUseCase()
            from apps.events.application.dtos import dto_to_event_publish_request
            use_case_request = dto_to_event_publish_request(use_case_request)
            use_case_response = use_case.execute(use_case_request)

            if use_case_response.success:
                return self.success_response(
                    data={
                        "event_id": use_case_response.event_id,
                        "published_at": use_case_response.published_at.isoformat(),
                        "subscribers_notified": use_case_response.subscribers_notified,
                    },
                    message="Event published successfully",
                )
            else:
                return self.error_response(
                    message=use_case_response.error_message or "Failed to publish event",
                    error_code="PUBLISH_FAILED",
                )

        except Exception as e:
            logger.error(f"Error in EventPublishView: {e}", exc_info=True)
            return self.error_response(
                message=str(e),
                error_code="INTERNAL_ERROR",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== 事件查询视图 ==========


class EventQueryView(BaseAPIView):
    """
    事件查询视图

    GET /api/events/query/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        """
        查询事件

        Args:
            request: HTTP 请求

        Returns:
            HTTP 响应
        """
        # 验证请求
        serializer = EventQueryRequestSerializer(data=request.query_params)
        if not serializer.is_valid():
            return self.error_response(
                message="Invalid query parameters",
                error_code="INVALID_QUERY",
            )

        data = serializer.validated_data

        try:
            # 解析事件类型
            event_type = None
            if data.get("event_type"):
                event_type = EventType(data["event_type"])

            event_types = None
            if data.get("event_types"):
                event_types = [EventType(et) for et in data["event_types"]]

            # 创建用例请求
            from apps.events.application.use_cases import QueryEventsRequest
            use_case_request = QueryEventsRequest(
                event_type=event_type,
                event_types=event_types,
                correlation_id=data.get("correlation_id"),
                since=data.get("since"),
                until=data.get("until"),
                limit=data.get("limit", 100),
            )

            # 执行用例
            use_case = QueryEventsUseCase()
            use_case_response = use_case.execute(use_case_request)

            if use_case_response.success:
                # 转换为序列化器格式
                events_data = [
                    {
                        "event_id": e.event_id,
                        "event_type": e.event_type,
                        "occurred_at": e.occurred_at.isoformat(),
                        "payload": e.payload,
                        "metadata": e.metadata,
                        "correlation_id": e.correlation_id,
                        "causation_id": e.causation_id,
                        "version": e.version,
                    }
                    for e in use_case_response.events
                ]

                return self.success_response(
                    data={
                        "events": events_data,
                        "total_count": use_case_response.total_count,
                        "queried_at": use_case_response.queried_at.isoformat(),
                        "has_more": use_case_response.total_count >= data.get("limit", 100),
                    },
                )
            else:
                return self.error_response(
                    message=use_case_response.error_message or "Failed to query events",
                    error_code="QUERY_FAILED",
                )

        except Exception as e:
            logger.error(f"Error in EventQueryView: {e}", exc_info=True)
            return self.error_response(
                message=str(e),
                error_code="INTERNAL_ERROR",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== 事件指标视图 ==========


class EventMetricsView(BaseAPIView):
    """
    事件指标视图

    GET /api/events/metrics/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        """
        获取事件指标

        Args:
            request: HTTP 请求

        Returns:
            HTTP 响应
        """
        try:
            # 执行用例
            use_case = GetEventMetricsUseCase()
            use_case_response = use_case.execute()

            # 转换为 DTO
            metrics_dto = metrics_to_dto(use_case_response)

            return self.success_response(
                data={
                    "metrics": {
                        "total_published": metrics_dto.total_published,
                        "total_processed": metrics_dto.total_processed,
                        "total_failed": metrics_dto.total_failed,
                        "total_subscribers": metrics_dto.total_subscribers,
                        "avg_processing_time_ms": metrics_dto.avg_processing_time_ms,
                        "last_event_at": metrics_dto.last_event_at,
                        "success_rate": metrics_dto.success_rate,
                    },
                    "events_by_type": use_case_response.events_by_type,
                    "active_subscriptions": metrics_dto.total_subscribers,
                    "queue_size": 0,  # 内存队列大小，暂不暴露
                },
            )

        except Exception as e:
            logger.error(f"Error in EventMetricsView: {e}", exc_info=True)
            return self.error_response(
                message=str(e),
                error_code="INTERNAL_ERROR",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== 事件总线状态视图 ==========


class EventBusStatusView(BaseAPIView):
    """
    事件总线状态视图

    GET /api/events/status/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        """
        获取事件总线状态

        Args:
            request: HTTP 请求

        Returns:
            HTTP 响应
        """
        try:
            from apps.events.domain.services import get_event_bus

            event_bus = get_event_bus()
            metrics = event_bus.get_metrics()

            return self.success_response(
                data={
                    "is_running": not event_bus._stopped if hasattr(event_bus, "_stopped") else True,
                    "total_subscribers": metrics.total_subscribers,
                    "queue_size": len(event_bus._event_queue) if hasattr(event_bus, "_event_queue") else 0,
                    "last_event_at": metrics.last_event_at.isoformat() if metrics.last_event_at else None,
                    "uptime_seconds": 0,  # 暂不跟踪运行时间
                },
            )

        except Exception as e:
            logger.error(f"Error in EventBusStatusView: {e}", exc_info=True)
            return self.error_response(
                message=str(e),
                error_code="INTERNAL_ERROR",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ========== 事件重放视图 ==========


class EventReplayView(BaseAPIView):
    """
    事件重放视图

    POST /api/events/replay/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        """
        重放事件

        Args:
            request: HTTP 请求

        Returns:
            HTTP 响应
        """
        # 验证请求
        serializer = EventReplayRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error_response(
                message="Invalid request data",
                error_code="INVALID_REQUEST",
            )

        data = serializer.validated_data

        try:
            # 解析事件类型
            event_type = None
            if data.get("event_type"):
                event_type = EventType(data["event_type"])

            # 创建用例请求
            from apps.events.application.use_cases import ReplayEventsRequest
            use_case_request = ReplayEventsRequest(
                event_type=event_type,
                since=data.get("since"),
                until=data.get("until"),
                limit=data.get("limit", 1000),
                target_handler=None,  # 暂不支持动态指定处理器
            )

            # 执行用例
            use_case = ReplayEventsUseCase()
            use_case_response = use_case.execute(use_case_request)

            if use_case_response.success:
                return self.success_response(
                    data={
                        "events_replayed": use_case_response.events_replayed,
                        "replayed_at": use_case_response.replayed_at.isoformat(),
                        "duration_ms": 0,
                    },
                    message=f"Replayed {use_case_response.events_replayed} events successfully",
                )
            else:
                return self.error_response(
                    message=use_case_response.error_message or "Failed to replay events",
                    error_code="REPLAY_FAILED",
                )

        except Exception as e:
            logger.error(f"Error in EventReplayView: {e}", exc_info=True)
            return self.error_response(
                message=str(e),
                error_code="INTERNAL_ERROR",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
