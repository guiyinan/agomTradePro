"""Legacy task-monitor API success and failure response contracts."""

from __future__ import annotations

from types import SimpleNamespace

from rest_framework.test import APIRequestFactory, force_authenticate

from apps.task_monitor.management import commands as views


def _request(path: str = "/"):
    request = APIRequestFactory().get(path)
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, pk=1))
    return request


class _Serializer:
    def __init__(self, value: object) -> None:
        self.data = value


def test_task_status_list_and_statistics_response_boundaries(monkeypatch) -> None:
    """Task queries preserve not-found, validation, success, and exception mappings."""
    monkeypatch.setattr(views, "TaskStatusSerializer", _Serializer)
    monkeypatch.setattr(views, "TaskListSerializer", _Serializer)
    monkeypatch.setattr(views, "TaskStatisticsSerializer", _Serializer)

    class _Status:
        def __init__(self, repository: object) -> None:
            pass

        def execute(self, task_id: str):
            return {"task_id": task_id} if task_id == "found" else None

    monkeypatch.setattr(views, "GetTaskStatusUseCase", _Status)
    assert views.get_task_status(_request(), "found").data["task_id"] == "found"
    assert views.get_task_status(_request(), "missing").status_code == 404

    class _List:
        def __init__(self, repository: object) -> None:
            pass

        def execute(self, **kwargs: object):
            return kwargs

    monkeypatch.setattr(views, "ListTasksUseCase", _List)
    listed = views.list_tasks(
        _request("/?task_name=sync&status=failure&limit=5&failures_only=true")
    )
    assert listed.data["limit"] == 5
    assert listed.data["failures_only"] is True

    class _Stats:
        def __init__(self, repository: object) -> None:
            pass

        def execute(self, **kwargs: object):
            return kwargs if kwargs["task_name"] == "sync" else None

    monkeypatch.setattr(views, "GetTaskStatisticsUseCase", _Stats)
    assert views.get_task_statistics(_request()).status_code == 400
    stats = views.get_task_statistics(_request("/?task_name=sync&days=14"))
    assert stats.data["days"] == 14
    assert views.get_task_statistics(_request("/?task_name=none")).status_code == 404

    class _BrokenStatus(_Status):
        def execute(self, task_id: str):
            raise RuntimeError("repository unavailable")

    monkeypatch.setattr(views, "GetTaskStatusUseCase", _BrokenStatus)
    assert views.get_task_status(_request(), "found").status_code == 500


def test_health_and_dashboard_success_and_failure_contracts(monkeypatch) -> None:
    """Health endpoints keep a structured degraded response when Celery is unavailable."""
    monkeypatch.setattr(views, "HealthCheckSerializer", _Serializer)
    health = SimpleNamespace(
        is_healthy=True,
        broker_reachable=True,
        backend_reachable=True,
        active_workers=["worker-1"],
        active_tasks_count=1,
        pending_tasks_count=2,
    )

    class _Health:
        def __init__(self, health_checker: object) -> None:
            pass

        def execute(self):
            return health

    class _List:
        def __init__(self, repository: object) -> None:
            pass

        def execute(self, **kwargs: object):
            return SimpleNamespace(total=1, items=[{"task": "failed"}])

    monkeypatch.setattr(views, "CheckCeleryHealthUseCase", _Health)
    monkeypatch.setattr(views, "ListTasksUseCase", _List)
    assert views.health_check(_request()).data.is_healthy is True
    dashboard = views.dashboard(_request())
    assert dashboard.data["recent_failures"]["count"] == 1
    assert dashboard.data["celery_health"]["active_workers_count"] == 1

    class _BrokenHealth(_Health):
        def execute(self):
            raise RuntimeError("broker unavailable")

    monkeypatch.setattr(views, "CheckCeleryHealthUseCase", _BrokenHealth)
    degraded = views.health_check(_request())
    assert degraded.status_code == 503
    assert degraded.data["is_healthy"] is False
    assert views.dashboard(_request()).status_code == 500
