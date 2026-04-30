import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.alpha.application.ops_locks import (
    build_qlib_data_refresh_lock_key,
    release_qlib_data_refresh_lock,
)

User = get_user_model()


def _build_superuser_client() -> Client:
    client = Client()
    user = User.objects.create_superuser(
        username=f"alpha-ops-admin-{uuid.uuid4().hex[:8]}",
        email=f"alpha-ops-admin-{uuid.uuid4().hex[:8]}@test.com",
        password="test-pass-123",
    )
    client.force_login(user)
    return client


def _build_staff_client() -> Client:
    client = Client()
    user = User.objects.create_user(
        username=f"alpha-ops-staff-{uuid.uuid4().hex[:8]}",
        email=f"alpha-ops-staff-{uuid.uuid4().hex[:8]}@test.com",
        password="test-pass-123",
        is_staff=True,
        is_superuser=False,
    )
    client.force_login(user)
    return client


def _patch_runtime_qlib_config_disabled(monkeypatch) -> None:
    fake_summary_service = SimpleNamespace(
        get_runtime_qlib_config=lambda: {
            "enabled": False,
            "provider_uri": "",
            "region": "CN",
            "model_path": "",
            "is_configured": False,
        }
    )
    monkeypatch.setattr(
        "apps.alpha.application.ops_services.get_account_config_summary_service",
        lambda: fake_summary_service,
    )


@pytest.mark.django_db
def test_qlib_data_refresh_api_immediately_exposes_pending_task_in_overview(monkeypatch):
    client = _build_superuser_client()
    _patch_runtime_qlib_config_disabled(monkeypatch)

    class FakeTask:
        id = "task-qlib-refresh-pending-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(**kwargs):
            return FakeTask()

    monkeypatch.setattr(
        "apps.alpha.application.tasks.qlib_refresh_runtime_data_task",
        FakeDelayWrapper,
    )

    target_date = date(2026, 4, 30)
    payload = {
        "mode": "universes",
        "target_date": target_date.isoformat(),
        "lookback_days": 400,
        "universes": ["csi300", "csi500"],
    }

    try:
        response = client.post(
            "/api/alpha/ops/qlib-data/refresh/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 202
        assert response["Content-Type"].startswith("application/json")
        body = response.json()
        assert body["success"] is True
        assert body["task_id"] == "task-qlib-refresh-pending-1"

        overview_response = client.get("/api/alpha/ops/qlib-data/overview/")
        assert overview_response.status_code == 200
        assert overview_response["Content-Type"].startswith("application/json")

        overview_payload = overview_response.json()
        assert overview_payload["success"] is True
        recent_tasks = overview_payload["data"]["recent_tasks"]
        matching = [
            item
            for item in recent_tasks
            if item["task_id"] == "task-qlib-refresh-pending-1"
        ]
        assert matching, "overview should include the just-queued pending task"
        task = matching[0]
        assert task["task_name"] == "apps.alpha.application.tasks.qlib_refresh_runtime_data_task"
        assert task["status"] == "pending"
        assert task["started_at"] is None
    finally:
        release_qlib_data_refresh_lock(
            build_qlib_data_refresh_lock_key(
                mode="universes",
                target_date=target_date,
                lookback_days=400,
                descriptor="csi300,csi500",
            )
        )


@pytest.mark.django_db
def test_qlib_data_page_renders_recent_pending_task_after_refresh(monkeypatch):
    client = _build_superuser_client()
    _patch_runtime_qlib_config_disabled(monkeypatch)

    class FakeTask:
        id = "task-qlib-refresh-pending-2"

    class FakeDelayWrapper:
        @staticmethod
        def delay(**kwargs):
            return FakeTask()

    monkeypatch.setattr(
        "apps.alpha.application.tasks.qlib_refresh_runtime_data_task",
        FakeDelayWrapper,
    )

    target_date = date(2026, 4, 30)
    payload = {
        "mode": "universes",
        "target_date": target_date.isoformat(),
        "lookback_days": 365,
        "universes": ["csi300"],
    }

    try:
        refresh_response = client.post(
            "/api/alpha/ops/qlib-data/refresh/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert refresh_response.status_code == 202

        page_response = client.get("/alpha/ops/qlib-data/")
        assert page_response.status_code == 200
        assert page_response["Content-Type"].startswith("text/html")
        html = page_response.content.decode(page_response.charset or "utf-8")

        assert "Qlib 基础数据管理" in html
        assert "apps.alpha.application.tasks.qlib_refresh_runtime_data_task" in html
        assert "pending" in html
        assert "暂无 Qlib 数据刷新任务记录。" not in html
    finally:
        release_qlib_data_refresh_lock(
            build_qlib_data_refresh_lock_key(
                mode="universes",
                target_date=target_date,
                lookback_days=365,
                descriptor="csi300",
            )
        )


@pytest.mark.django_db
def test_qlib_data_ops_permissions_allow_staff_read_but_block_write(monkeypatch):
    client = _build_staff_client()
    _patch_runtime_qlib_config_disabled(monkeypatch)

    overview_response = client.get("/api/alpha/ops/qlib-data/overview/")
    assert overview_response.status_code == 200
    assert overview_response.json()["success"] is True

    refresh_response = client.post(
        "/api/alpha/ops/qlib-data/refresh/",
        data=json.dumps(
            {
                "mode": "universes",
                "target_date": "2026-04-30",
                "lookback_days": 400,
                "universes": ["csi300"],
            }
        ),
        content_type="application/json",
    )
    assert refresh_response.status_code == 403
    assert refresh_response["Content-Type"].startswith("application/json")
    assert refresh_response.json()["error"] == "需要 superuser 权限"
