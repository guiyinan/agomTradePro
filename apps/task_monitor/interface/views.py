"""
Task Monitor Interface Views

DRF 视图定义。
"""

import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.task_monitor.application.use_cases import (
    CheckCeleryHealthUseCase,
    GetTaskStatisticsUseCase,
    GetTaskStatusUseCase,
    ListTasksUseCase,
)
from apps.task_monitor.infrastructure.repositories import (
    CeleryHealthChecker,
    DjangoTaskRecordRepository,
)
from apps.task_monitor.interface.serializers import (
    HealthCheckSerializer,
    TaskListSerializer,
    TaskStatisticsSerializer,
    TaskStatusRequestSerializer,
    TaskStatusSerializer,
)

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["Task Monitor"],
    summary="获取任务状态",
    description="根据任务 ID 获取任务的执行状态",
    responses={
        200: TaskStatusSerializer,
        404: {"description": "任务不存在"},
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_task_status(request, task_id: str) -> Response:
    """
    获取任务状态

    GET /api/system/tasks/status/{task_id}/
    """
    try:
        use_case = GetTaskStatusUseCase(repository=DjangoTaskRecordRepository())
        result = use_case.execute(task_id=task_id)

        if not result:
            return Response(
                {"error": "Task not found", "code": "TASK_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = TaskStatusSerializer(result)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
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
@permission_classes([IsAuthenticated])
def list_tasks(request) -> Response:
    """
    列出任务

    GET /api/system/tasks/list/
    """
    try:
        task_name = request.query_params.get("task_name")
        status_filter = request.query_params.get("status")
        limit = int(request.query_params.get("limit", 100))
        failures_only = request.query_params.get("failures_only", "false").lower() == "true"

        use_case = ListTasksUseCase(repository=DjangoTaskRecordRepository())
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
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
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
@permission_classes([IsAuthenticated])
def get_task_statistics(request) -> Response:
    """
    获取任务统计

    GET /api/system/tasks/statistics/
    """
    try:
        task_name = request.query_params.get("task_name")
        if not task_name:
            return Response(
                {"error": "task_name is required", "code": "MISSING_PARAMETER"},
                status=status.HTTP_400_BAD_REQUEST
            )

        days = int(request.query_params.get("days", 7))

        use_case = GetTaskStatisticsUseCase(repository=DjangoTaskRecordRepository())
        result = use_case.execute(task_name=task_name, days=days)

        if not result:
            return Response(
                {"error": "No statistics found for this task", "code": "NO_STATISTICS"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = TaskStatisticsSerializer(result)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Failed to get task statistics: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    tags=["Task Monitor"],
    summary="Celery 健康检查",
    description="检查 Celery 服务的健康状态（Broker 连接、Backend 连接、Worker 状态等）",
    responses={200: HealthCheckSerializer},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def health_check(request) -> Response:
    """
    Celery 健康检查

    GET /api/system/celery/health/
    """
    try:
        from core.celery import app as celery_app

        health_checker = CeleryHealthChecker(celery_app=celery_app)
        use_case = CheckCeleryHealthUseCase(health_checker=health_checker)
        result = use_case.execute()

        serializer = HealthCheckSerializer(result)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Failed to check Celery health: {e}")
        # 即使健康检查失败，也返回一个健康状态对象
        return Response({
            "is_healthy": False,
            "broker_reachable": False,
            "backend_reachable": False,
            "active_workers": [],
            "active_tasks_count": 0,
            "pending_tasks_count": 0,
            "scheduled_tasks_count": 0,
            "last_check": None,
            "error": str(e),
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@extend_schema(
    tags=["Task Monitor"],
    summary="任务监控概览",
    description="获取任务监控的概览信息（最近失败的任务、活跃的 Worker 等）",
    responses={200: dict},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard(request) -> Response:
    """
    任务监控概览

    GET /api/system/tasks/dashboard/
    """
    try:
        from core.celery import app as celery_app

        # 获取最近的失败任务
        list_use_case = ListTasksUseCase(repository=DjangoTaskRecordRepository())
        failures = list_use_case.execute(failures_only=True, limit=10)

        # 检查 Celery 健康状态
        health_checker = CeleryHealthChecker(celery_app=celery_app)
        health_use_case = CheckCeleryHealthUseCase(health_checker=health_checker)
        health = health_use_case.execute()

        return Response({
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
        })

    except Exception as e:
        logger.error(f"Failed to get dashboard: {e}")
        return Response(
            {"error": str(e), "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
