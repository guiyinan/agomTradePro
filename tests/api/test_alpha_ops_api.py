import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.alpha.infrastructure.models import (
    AlphaAlertModel,
    AlphaScoreCacheModel,
    QlibModelRegistryModel,
)
from apps.config_center.infrastructure.models import SystemSettingsModel
from apps.task_monitor.infrastructure.models import TaskExecutionModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="alpha_ops_staff",
        password="testpass123",
        email="alpha-ops-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_user(
        username="alpha_ops_admin",
        password="testpass123",
        email="alpha-ops-admin@example.com",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def normal_user(db):
    return get_user_model().objects.create_user(
        username="alpha_ops_normal",
        password="testpass123",
        email="alpha-ops-normal@example.com",
    )


@pytest.mark.django_db
def test_alpha_api_root_exposes_ops_endpoints():
    response = APIClient().get("/api/alpha/")

    assert response.status_code == 200
    payload = response.json()
    assert "/api/alpha/ops/inference/overview/" in payload["endpoints"]
    assert "/api/alpha/ops/qlib-data/refresh/" in payload["endpoints"]


@pytest.mark.django_db
def test_alpha_ops_overview_requires_staff(api_client, normal_user):
    api_client.force_authenticate(user=normal_user)

    response = api_client.get("/api/alpha/ops/inference/overview/")
    assert response.status_code == 403

    response = api_client.get("/api/alpha/ops/qlib-data/overview/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_alpha_ops_overview_returns_use_case_payload_for_staff(api_client, staff_user, monkeypatch):
    class FakeInferenceOverviewUseCase:
        def execute(self):
            return {"active_model": {"model_name": "alpha-v1"}, "recent_tasks": []}

    class FakeQlibOverviewUseCase:
        def execute(self):
            return {"local_data_status": {"latest_trade_date": "2026-04-28"}}

    api_client.force_authenticate(user=staff_user)
    monkeypatch.setattr(
        "apps.alpha.interface.views.GetAlphaInferenceOpsOverviewUseCase",
        FakeInferenceOverviewUseCase,
    )
    monkeypatch.setattr(
        "apps.alpha.interface.views.GetQlibDataOpsOverviewUseCase",
        FakeQlibOverviewUseCase,
    )

    response = api_client.get("/api/alpha/ops/inference/overview/")
    assert response.status_code == 200
    assert response.json()["data"]["active_model"]["model_name"] == "alpha-v1"

    response = api_client.get("/api/alpha/ops/qlib-data/overview/")
    assert response.status_code == 200
    assert response.json()["data"]["local_data_status"]["latest_trade_date"] == "2026-04-28"


@pytest.mark.django_db
def test_alpha_ops_overviews_default_chain_are_pure_staff_reads(
    api_client,
    staff_user,
    monkeypatch,
):
    api_client.force_authenticate(user=staff_user)
    SystemSettingsModel._default_manager.all().delete()
    monkeypatch.setattr(
        "apps.alpha.application.ops_services.AlphaOpsOverviewQueryService._get_celery_health",
        lambda _self: {
            "is_healthy": True,
            "broker_reachable": True,
            "backend_reachable": True,
            "active_workers": [],
            "active_tasks_count": 0,
            "pending_tasks_count": 0,
            "scheduled_tasks_count": 0,
            "last_check": "2026-07-11T00:00:00+00:00",
        },
    )

    tracked_models = (
        SystemSettingsModel,
        QlibModelRegistryModel,
        AlphaScoreCacheModel,
        AlphaAlertModel,
        TaskExecutionModel,
    )
    counts_before = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }

    inference_response = api_client.get("/api/alpha/ops/inference/overview/")
    qlib_data_response = api_client.get("/api/alpha/ops/qlib-data/overview/")

    assert inference_response.status_code == 200
    inference_payload = inference_response.json()
    assert inference_payload["success"] is True
    assert set(inference_payload["data"]) == {
        "active_model",
        "qlib_runtime",
        "celery_health",
        "dashboard_refresh_locks",
        "recent_tasks",
        "recent_caches",
        "recent_alerts",
    }
    assert qlib_data_response.status_code == 200
    qlib_data_payload = qlib_data_response.json()
    assert qlib_data_payload["success"] is True
    assert set(qlib_data_payload["data"]) == {
        "qlib_runtime",
        "local_data_status",
        "recent_tasks",
        "latest_build_summary",
    }

    counts_after = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }
    assert counts_after == counts_before
    assert SystemSettingsModel._default_manager.count() == 0


@pytest.mark.django_db
def test_alpha_ops_post_requires_superuser(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)

    response = api_client.post(
        "/api/alpha/ops/inference/trigger/",
        {"mode": "general", "trade_date": "2026-04-28", "top_n": 10, "universe_id": "csi300"},
        format="json",
    )
    assert response.status_code == 403

    response = api_client.post(
        "/api/alpha/ops/qlib-data/refresh/",
        {"mode": "universes", "target_date": "2026-04-28", "universes": ["csi300"]},
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_alpha_ops_post_returns_accepted_for_superuser(api_client, superuser, monkeypatch):
    class FakeTriggerUseCase:
        def execute(self, **kwargs):
            return {"success": True, "task_id": "task-123", "message": "queued"}

    api_client.force_authenticate(user=superuser)
    monkeypatch.setattr(
        "apps.alpha.interface.views.TriggerGeneralInferenceUseCase",
        FakeTriggerUseCase,
    )
    monkeypatch.setattr(
        "apps.alpha.interface.views.TriggerQlibUniverseRefreshUseCase",
        FakeTriggerUseCase,
    )

    response = api_client.post(
        "/api/alpha/ops/inference/trigger/",
        {"mode": "general", "trade_date": "2026-04-28", "top_n": 10, "universe_id": "csi300"},
        format="json",
    )
    assert response.status_code == 202
    assert response.json()["task_id"] == "task-123"

    response = api_client.post(
        "/api/alpha/ops/qlib-data/refresh/",
        {
            "mode": "universes",
            "target_date": "2026-04-28",
            "lookback_days": 400,
            "universes": ["csi300"],
        },
        format="json",
    )
    assert response.status_code == 202
    assert response.json()["task_id"] == "task-123"
