"""
Task Monitor Interface Views

DRF 视图定义。
"""

import logging
from collections.abc import Callable
from typing import ParamSpec, Protocol, TypeVar, cast

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.task_monitor.application.interface_services import (
    bootstrap_scheduler_defaults,
    configure_readiness_schedule,
    get_readiness_monitor_context,
    get_readiness_schedule_payload,
    get_scheduler_console_payload,
)
from apps.task_monitor.application.repository_provider import (
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
    ReadinessMonitorQuerySerializer,
    ReadinessScheduleUpdateSerializer,
    SchedulerConsoleQuerySerializer,
    TaskListSerializer,
    TaskStatisticsSerializer,
    TaskStatusSerializer,
)

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _PreservingDecorator(Protocol):
    """Describe a third-party decorator that preserves a callable signature."""

    def __call__(self, func: Callable[_P, _R], /) -> Callable[_P, _R]: ...


def _typed_decorator(decorator: object) -> _PreservingDecorator:
    """Narrow an untyped framework decorator without changing runtime behavior."""

    return cast(_PreservingDecorator, decorator)


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="读取计划任务管理台",
        responses={200: dict},
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAdminUser]))
def scheduler_console(request: Request) -> Response:
    """Return the bounded administrator scheduler console payload."""

    query = SchedulerConsoleQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    limit = query.validated_data.get("limit", 100)
    return Response(get_scheduler_console_payload(limit=limit))


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="初始化默认计划任务",
        responses={200: dict},
    )
)
@_typed_decorator(api_view(["POST"]))
@_typed_decorator(permission_classes([IsAdminUser]))
def bootstrap_scheduler(request: Request) -> Response:
    """Initialize the repository-owned default periodic tasks."""

    return Response(bootstrap_scheduler_defaults())


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="读取 readiness 验收状态",
        responses={200: dict},
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAdminUser]))
def readiness_monitor(request: Request) -> Response:
    """Return readiness status with an optional strict runtime probe."""

    query = ReadinessMonitorQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    return Response(
        get_readiness_monitor_context(
            strict_runtime=query.validated_data["strict_runtime"],
        )
    )


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="读取或更新 readiness 调度时间",
        request=ReadinessScheduleUpdateSerializer,
        responses={200: dict},
    )
)
@_typed_decorator(api_view(["GET", "PATCH"]))
@_typed_decorator(permission_classes([IsAdminUser]))
def readiness_schedule(request: Request) -> Response:
    """Read or update the three post-close readiness schedule times."""

    if request.method == "GET":
        return Response(get_readiness_schedule_payload())

    serializer = ReadinessScheduleUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response(configure_readiness_schedule(**serializer.validated_data))


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="获取任务状态",
        description="根据任务 ID 获取任务的执行状态",
        responses={
            200: TaskStatusSerializer,
            404: {"description": "任务不存在"},
        },
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAuthenticated]))
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

    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="列出任务",
        description="列出任务执行记录，支持按任务名称、状态过滤",
        parameters=[
            OpenApiParameter(
                name="task_name",
                description="任务名称过滤",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="status",
                description="状态过滤 (pending/started/success/failure/retry/revoked/timeout)",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="limit",
                description="返回数量限制",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name="failures_only",
                description="只返回失败的任务",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
        ],
        responses={200: TaskListSerializer},
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAuthenticated]))
def list_tasks(request: Request) -> Response:
    """
    列出任务

    GET /api/system/tasks/list/
    """
    try:
        task_name = request.query_params.get("task_name")
        status_filter = request.query_params.get("status")
        limit = int(request.query_params.get("limit", 100))
        failures_only = request.query_params.get("failures_only", "false").lower() == "true"

        use_case = ListTasksUseCase(repository=get_task_record_repository())
        result = use_case.execute(
            task_name=task_name,
            status=status_filter,
            limit=limit,
            failures_only=failures_only,
        )

        serializer = TaskListSerializer(result)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="获取任务统计",
        description="获取指定任务的统计信息（成功率、平均运行时长等）",
        parameters=[
            OpenApiParameter(
                name="task_name",
                description="任务名称",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
            ),
            OpenApiParameter(
                name="days",
                description="统计最近多少天",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
        ],
        responses={
            200: TaskStatisticsSerializer,
            404: {"description": "任务不存在或无统计数据"},
        },
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAuthenticated]))
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

        days = int(request.query_params.get("days", 7))

        use_case = GetTaskStatisticsUseCase(repository=get_task_record_repository())
        result = use_case.execute(task_name=task_name, days=days)

        if not result:
            return Response(
                {"error": "No statistics found for this task", "code": "NO_STATISTICS"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TaskStatisticsSerializer(result)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Failed to get task statistics: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="Celery 健康检查",
        description="检查 Celery 服务的健康状态（Broker 连接、Backend 连接、Worker 状态等）",
        responses={200: HealthCheckSerializer},
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAuthenticated]))
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

    except Exception as e:
        logger.error(f"Failed to check Celery health: {e}")
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
                "error": str(e),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@_typed_decorator(
    extend_schema(
        tags=["Task Monitor"],
        summary="任务监控概览",
        description="获取任务监控的概览信息（最近失败的任务、活跃的 Worker 等）",
        responses={200: dict},
    )
)
@_typed_decorator(api_view(["GET"]))
@_typed_decorator(permission_classes([IsAuthenticated]))
def dashboard(request: Request) -> Response:
    """
    任务监控概览

    GET /api/system/tasks/dashboard/
    """
    try:
        # 获取最近的失败任务
        list_use_case = ListTasksUseCase(repository=get_task_record_repository())
        failures = list_use_case.execute(failures_only=True, limit=10)

        # 检查 Celery 健康状态
        health_use_case = CheckCeleryHealthUseCase(health_checker=get_celery_health_checker())
        health = health_use_case.execute()

        return Response(
            {
                "recent_failures": {
                    "count": failures.total,
                    "items": TaskStatusSerializer(failures.items, many=True).data,
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

    except Exception as e:
        logger.error(f"Failed to get dashboard: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
