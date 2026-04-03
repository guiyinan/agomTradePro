from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.task_monitor.domain.entities import CeleryHealthStatus, TaskExecutionRecord, TaskPriority, TaskStatus
from apps.task_monitor.infrastructure.models import TaskExecutionModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="task_monitor_user",
        password="testpass123",
        email="task-monitor@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_get_task_status_returns_serialized_task(authenticated_client):
    now = timezone.now()
    TaskExecutionModel.objects.create(
        task_id="task-123",
        task_name="demo.task",
        status="success",
        args=["a"],
        kwargs={"k": "v"},
        started_at=now - timedelta(seconds=5),
        finished_at=now,
        runtime_seconds=5.0,
        result="OK",
        retries=1,
        priority="high",
        queue="default",
        worker="worker@node",
    )

    response = authenticated_client.get("/api/system/status/task-123/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["task_id"] == "task-123"
    assert payload["task_name"] == "demo.task"
    assert payload["status"] == "success"
    assert payload["is_success"] is True
    assert payload["is_failure"] is False


@pytest.mark.django_db
def test_get_task_statistics_requires_task_name(authenticated_client):
    response = authenticated_client.get("/api/system/statistics/")

    assert response.status_code == 400
    assert response.json() == {
        "error": "task_name is required",
        "code": "MISSING_PARAMETER",
    }


@pytest.mark.django_db
def test_get_task_statistics_returns_summary(authenticated_client):
    now = timezone.now()
    TaskExecutionModel.objects.create(
        task_id="success-1",
        task_name="stats.task",
        status="success",
        args=[],
        kwargs={},
        started_at=now - timedelta(seconds=12),
        finished_at=now - timedelta(seconds=2),
        runtime_seconds=10.0,
        result="OK",
        retries=0,
        priority="normal",
    )
    TaskExecutionModel.objects.create(
        task_id="failure-1",
        task_name="stats.task",
        status="failure",
        args=[],
        kwargs={},
        started_at=now - timedelta(seconds=30),
        finished_at=now - timedelta(seconds=20),
        runtime_seconds=10.0,
        exception="boom",
        retries=1,
        priority="normal",
    )

    response = authenticated_client.get("/api/system/statistics/?task_name=stats.task&days=7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_name"] == "stats.task"
    assert payload["total_executions"] == 2
    assert payload["successful_executions"] == 1
    assert payload["failed_executions"] == 1
    assert payload["average_runtime"] == 10.0
    assert payload["success_rate"] == 0.5
    assert payload["last_execution_status"] in {"success", "failure"}


@pytest.mark.django_db
def test_health_check_returns_service_unavailable_payload_on_exception(authenticated_client):
    with patch(
        "apps.task_monitor.interface.views.CheckCeleryHealthUseCase.execute",
        side_effect=RuntimeError("broker offline"),
    ):
        response = authenticated_client.get("/api/system/celery/health/")

    assert response.status_code == 503
    payload = response.json()
    assert payload["is_healthy"] is False
    assert payload["broker_reachable"] is False
    assert payload["backend_reachable"] is False
    assert payload["active_workers"] == []
    assert payload["error"] == "broker offline"


@pytest.mark.django_db
def test_dashboard_aggregates_recent_failures_and_health(authenticated_client):
    now = timezone.now()
    failures = SimpleNamespace(
        total=1,
        items=[
            TaskExecutionRecord(
                task_id="failed-1",
                task_name="demo.task",
                status=TaskStatus.FAILURE,
                args=(),
                kwargs={},
                started_at=now - timedelta(seconds=4),
                finished_at=now,
                result=None,
                exception="boom",
                traceback=None,
                runtime_seconds=4.0,
                retries=2,
                priority=TaskPriority.HIGH,
                queue="critical",
                worker="worker@node",
            )
        ],
    )
    health = CeleryHealthStatus(
        is_healthy=True,
        broker_reachable=True,
        backend_reachable=True,
        active_workers=["worker@node"],
        active_tasks_count=2,
        pending_tasks_count=1,
        scheduled_tasks_count=0,
        last_check=now,
    )

    with patch(
        "apps.task_monitor.interface.views.ListTasksUseCase.execute",
        return_value=failures,
    ) as mock_list, patch(
        "apps.task_monitor.interface.views.CheckCeleryHealthUseCase.execute",
        return_value=health,
    ) as mock_health:
        response = authenticated_client.get("/api/system/dashboard/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recent_failures"]["count"] == 1
    assert payload["celery_health"]["is_healthy"] is True
    assert payload["celery_health"]["active_workers_count"] == 1
    assert payload["celery_health"]["active_tasks_count"] == 2
    mock_list.assert_called_once_with(failures_only=True, limit=10)
    mock_health.assert_called_once()
