"""Typed Task Monitor serializer contracts."""

from apps.task_monitor.application.dtos import (
    HealthCheckResponse,
    TaskListResponse,
    TaskStatisticsResponse,
    TaskStatusResponse,
)
from apps.task_monitor.interface.serializers import (
    HealthCheckSerializer,
    TaskListSerializer,
    TaskStatisticsSerializer,
    TaskStatusRequestSerializer,
)


def _task_status() -> TaskStatusResponse:
    """Build one representative Application response DTO."""

    return TaskStatusResponse(
        task_id="task-1",
        task_name="sync_macro_data",
        status="success",
        started_at="2026-07-27T09:00:00+00:00",
        finished_at="2026-07-27T09:00:01+00:00",
        runtime_seconds=1.0,
        retries=0,
        is_success=True,
        is_failure=False,
    )


def test_response_serializers_accept_application_dtos() -> None:
    """Response serializers preserve the DTO contracts emitted by use cases."""

    listed = TaskListSerializer(TaskListResponse(total=1, items=[_task_status()])).data
    health = HealthCheckSerializer(
        HealthCheckResponse(
            is_healthy=True,
            broker_reachable=True,
            backend_reachable=True,
            active_workers=["worker-1"],
            active_tasks_count=1,
            pending_tasks_count=2,
            scheduled_tasks_count=3,
            last_check="2026-07-27T09:00:00+00:00",
        )
    ).data
    statistics = TaskStatisticsSerializer(
        TaskStatisticsResponse(
            task_name="sync_macro_data",
            total_executions=10,
            successful_executions=9,
            failed_executions=1,
            average_runtime=2.5,
            success_rate=0.9,
            last_execution_status="success",
            last_execution_at="2026-07-27T09:00:01+00:00",
        )
    ).data

    assert listed["items"][0]["task_id"] == "task-1"
    assert health["active_workers"] == ["worker-1"]
    assert statistics["success_rate"] == 0.9


def test_task_status_request_serializer_requires_non_blank_task_id() -> None:
    """The request serializer rejects missing or blank task identities."""

    missing = TaskStatusRequestSerializer(data={})
    blank = TaskStatusRequestSerializer(data={"task_id": ""})
    valid = TaskStatusRequestSerializer(data={"task_id": "task-1"})

    assert missing.is_valid() is False
    assert blank.is_valid() is False
    assert valid.is_valid() is True
    assert valid.validated_data == {"task_id": "task-1"}
