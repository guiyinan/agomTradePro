"""
Task Monitor Interface Views

DRF 视图定义。
"""

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.task_monitor.application.provider import (
    get_celery_health_checker,
    get_task_record_repository,
)
from apps.task_monitor.application.use_cases import (
    CheckCeleryHealthUseCase,
    GetTaskStatisticsUseCase,
    GetTaskStatusUseCase,
    ListTasksUseCase,
)
from apps.task_monitor.interface.serializers import (
    HealthCheckSerializer,
    TaskListSerializer,
    TaskStatisticsSerializer,
    TaskStatusSerializer,
)

logger = logging.getLogger(__name__)

ViewMethod = TypeVar("ViewMethod", bound=Callable[..., object])

_TASK_STATUS_VALUES = frozenset(
    {"pending", "started", "success", "failure", "retry", "revoked", "timeout"}
)


def typed_schema(*args: Any, **kwargs: Any) -> Callable[[ViewMethod], ViewMethod]:
    """Narrow drf-spectacular's dynamic decorator at the third-party boundary."""

    return cast(Callable[[ViewMethod], ViewMethod], extend_schema(*args, **kwargs))


def _parse_positive_int(raw_value: str | None, *, field_name: str, default: int) -> int:
    """Parse a positive integer query parameter."""

    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return value


def _parse_bool(raw_value: str | None, *, field_name: str, default: bool) -> bool:
    """Parse a strict boolean query parameter."""

    if raw_value is None or raw_value == "":
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"{field_name} must be a boolean")


def _internal_error(operation: str) -> Response:
    """Log the active exception and return a stable public error."""

    logger.exception("Task monitor operation failed: %s", operation)
    return Response(
        {"error": "Task monitor operation failed", "code": "INTERNAL_ERROR"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@typed_schema(
    tags=["Task Monitor"],
    summary="获取任务状态",
    description="根据任务 ID 获取任务的执行状态",
    responses={
        200: TaskStatusSerializer,
        404: {"description": "任务不存在"},
    },
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_task_status(request: Request, task_id: str) -> Response:
    """
    获取任务状态

    GET /api/system/tasks/status/{task_id}/
    """
    try:
        use_case = GetTaskStatusUseCase(repository=get_task_record_repository())
        result = use_case.execute(task_id=task_id)

        if not result:
            return Response(
                {"error": "Task not found", "code": "TASK_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TaskStatusSerializer(result)
        return Response(serializer.data)

    except Exception:
        return _internal_error("get_task_status")


@typed_schema(
    tags=["Task Monitor"],
    summary="列出任务",
    description="列出任务执行记录，支持按任务名称、状态过滤",
    parameters=[
        OpenApiParameter(
            name="task_name",
            description="任务名称过滤",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
        OpenApiParameter(
            name="status",
            description="状态过滤 (pending/started/success/failure/retry/revoked/timeout)",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
        OpenApiParameter(
            name="limit",
            description="返回数量限制",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
        OpenApiParameter(
            name="failures_only",
            description="只返回失败的任务",
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={200: TaskListSerializer},
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def list_tasks(request: Request) -> Response:
    """
    列出任务

    GET /api/system/tasks/list/
    """
    try:
        task_name = request.query_params.get("task_name")
        status_filter = request.query_params.get("status")
        if status_filter and status_filter not in _TASK_STATUS_VALUES:
            return Response(
                {"error": "status is invalid", "code": "INVALID_PARAMETER"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = _parse_positive_int(
            request.query_params.get("limit"),
            field_name="limit",
            default=100,
        )
        failures_only = _parse_bool(
            request.query_params.get("failures_only"),
            field_name="failures_only",
            default=False,
        )

        use_case = ListTasksUseCase(repository=get_task_record_repository())
        result = use_case.execute(
            task_name=task_name,
            status=status_filter,
            limit=limit,
            failures_only=failures_only,
        )

        serializer = TaskListSerializer(result)
        return Response(serializer.data)

    except ValueError as exc:
        return Response(
            {"error": str(exc), "code": "INVALID_PARAMETER"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        return _internal_error("list_tasks")


@typed_schema(
    tags=["Task Monitor"],
    summary="获取任务统计",
    description="获取指定任务的统计信息（成功率、平均运行时长等）",
    parameters=[
        OpenApiParameter(
            name="task_name",
            description="任务名称",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
        ),
        OpenApiParameter(
            name="days",
            description="统计最近多少天",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            required=False,
        ),
    ],
    responses={
        200: TaskStatisticsSerializer,
        404: {"description": "任务不存在或无统计数据"},
    },
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_task_statistics(request: Request) -> Response:
    """
    获取任务统计

    GET /api/system/tasks/statistics/
    """
    try:
        task_name = request.query_params.get("task_name")
        if not task_name:
            return Response(
                {"error": "task_name is required", "code": "MISSING_PARAMETER"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        days = _parse_positive_int(
            request.query_params.get("days"),
            field_name="days",
            default=7,
        )

        use_case = GetTaskStatisticsUseCase(repository=get_task_record_repository())
        result = use_case.execute(task_name=task_name, days=days)

        if not result:
            return Response(
                {"error": "No statistics found for this task", "code": "NO_STATISTICS"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TaskStatisticsSerializer(result)
        return Response(serializer.data)

    except ValueError as exc:
        return Response(
            {"error": str(exc), "code": "INVALID_PARAMETER"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        return _internal_error("get_task_statistics")


@typed_schema(
    tags=["Task Monitor"],
    summary="Celery 健康检查",
    description="检查 Celery 服务的健康状态（Broker 连接、Backend 连接、Worker 状态等）",
    responses={200: HealthCheckSerializer},
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def health_check(request: Request) -> Response:
    """
    Celery 健康检查

    GET /api/system/celery/health/
    """
    try:
        use_case = CheckCeleryHealthUseCase(health_checker=get_celery_health_checker())
        result = use_case.execute()

        serializer = HealthCheckSerializer(result)
        return Response(serializer.data)

    except Exception:
        logger.exception("Task monitor operation failed: health_check")
        # 即使健康检查失败，也返回一个健康状态对象
        return Response(
            {
                "is_healthy": False,
                "broker_reachable": False,
                "backend_reachable": False,
                "active_workers": [],
                "active_tasks_count": 0,
                "pending_tasks_count": 0,
                "scheduled_tasks_count": 0,
                "last_check": None,
                "error": "health_check_failed",
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@typed_schema(
    tags=["Task Monitor"],
    summary="任务监控概览",
    description="获取任务监控的概览信息（最近失败的任务、活跃的 Worker 等）",
    responses={200: OpenApiTypes.OBJECT},
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def dashboard(request: Request) -> Response:
    """
    任务监控概览

    GET /api/system/tasks/dashboard/
    """
    try:
        # 获取最近的失败任务
        list_use_case = ListTasksUseCase(repository=get_task_record_repository())
        failures = list_use_case.execute(failures_only=True, limit=10)
        failure_payload = TaskListSerializer(failures).data

        # 检查 Celery 健康状态
        health_use_case = CheckCeleryHealthUseCase(health_checker=get_celery_health_checker())
        health = health_use_case.execute()

        return Response(
            {
                "recent_failures": {
                    "count": failure_payload["total"],
                    "items": failure_payload["items"],
                },
                "celery_health": {
                    "is_healthy": health.is_healthy,
                    "broker_reachable": health.broker_reachable,
                    "backend_reachable": health.backend_reachable,
                    "active_workers_count": len(health.active_workers),
                    "active_tasks_count": health.active_tasks_count,
                    "pending_tasks_count": health.pending_tasks_count,
                },
            }
        )

    except Exception:
        return _internal_error("dashboard")
