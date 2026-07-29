from datetime import date

import pytest
from django.apps import apps as django_apps

from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.domain.entities import TaskStatus


@pytest.fixture
def staff_client(api_client, auth_user):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_policy_status_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.get("/api/policy/status/?as_of_date=2026/04/02")

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error"] == "Invalid query parameters"


@pytest.mark.django_db
def test_policy_workbench_items_rejects_invalid_tab(authenticated_client):
    response = authenticated_client.get("/api/policy/workbench/items/?tab=invalid")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "tab" in payload["errors"]


@pytest.mark.django_db
def test_policy_reject_event_requires_reason(authenticated_client):
    response = authenticated_client.post(
        "/api/policy/workbench/items/123/reject/",
        {},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "reason" in payload["errors"]


@pytest.mark.django_db
def test_policy_workbench_fetch_rejects_invalid_source_id(staff_client):
    response = staff_client.post(
        "/api/policy/workbench/fetch/",
        {"source_id": "not-an-int"},
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "source_id" in payload["errors"]


@pytest.mark.django_db
def test_policy_rss_trigger_fetch_records_pending_task_immediately(
    staff_client,
    monkeypatch,
    settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = False

    source_model = django_apps.get_model("policy", "RSSSourceConfigModel")
    source = source_model.objects.create(
        name="Policy Feed",
        url="https://example.com/feed.xml",
        is_active=True,
        category="policy",
    )

    class FakeTask:
        id = "rss-task-1"

    class FakeDelayWrapper:
        @staticmethod
        def delay(*, source_id=None):
            assert source_id == source.id
            return FakeTask()

    monkeypatch.setattr("apps.policy.application.tasks.fetch_rss_sources", FakeDelayWrapper)

    response = staff_client.post(
        f"/api/policy/rss/sources/{source.id}/trigger_fetch/",
        {},
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "triggered"
    assert payload["task_id"] == "rss-task-1"

    record = get_task_record_repository().get_by_task_id("rss-task-1")
    assert record is not None
    assert record.status == TaskStatus.PENDING
    assert record.task_name == "apps.policy.application.tasks.fetch_rss_sources"
    assert record.kwargs == {"source_id": source.id}


@pytest.mark.django_db
def test_policy_rss_fetch_all_records_pending_task_immediately(
    staff_client,
    monkeypatch,
    settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = False

    class FakeTask:
        id = "rss-task-2"

    class FakeDelayWrapper:
        @staticmethod
        def delay(*, source_id=None):
            assert source_id is None
            return FakeTask()

    monkeypatch.setattr("apps.policy.application.tasks.fetch_rss_sources", FakeDelayWrapper)

    response = staff_client.post(
        "/api/policy/rss/sources/fetch_all/",
        {},
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "triggered"
    assert payload["task_id"] == "rss-task-2"

    record = get_task_record_repository().get_by_task_id("rss-task-2")
    assert record is not None
    assert record.status == TaskStatus.PENDING
    assert record.task_name == "apps.policy.application.tasks.fetch_rss_sources"
    assert record.kwargs == {"source_id": None}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/policy/rss/sources/"),
        ("get", "/api/policy/rss/logs/"),
        ("get", "/api/policy/rss/keywords/"),
        ("post", "/api/policy/rss/sources/fetch_all/"),
    ],
)
def test_policy_rss_management_requires_staff(
    authenticated_client,
    method,
    path,
):
    response = getattr(authenticated_client, method)(path, {}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_policy_rss_source_access_key_is_write_only(staff_client):
    response = staff_client.post(
        "/api/policy/rss/sources/",
        {
            "name": "Secret Feed",
            "url": "https://example.com/feed.xml",
            "category": "other",
            "is_active": True,
            "fetch_interval_hours": 6,
            "rsshub_enabled": True,
            "rsshub_use_global_config": False,
            "rsshub_custom_base_url": "https://rsshub.example.com",
            "rsshub_custom_access_key": "top-secret-key",
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert "rsshub_custom_access_key" not in payload
    detail = staff_client.get(f"/api/policy/rss/sources/{payload['id']}/")
    assert detail.status_code == 200
    assert "rsshub_custom_access_key" not in detail.json()


@pytest.mark.django_db
def test_policy_event_create_classic_page_requires_staff(client, test_user):
    assert client.get("/policy/events/new/").status_code == 302

    client.force_login(test_user)
    assert client.get("/policy/events/new/").status_code == 403

    test_user.is_staff = True
    test_user.save(update_fields=["is_staff"])
    client.force_login(test_user)
    assert client.get("/policy/events/new/").status_code == 200


@pytest.mark.django_db
def test_policy_rss_governance_pages_require_staff_but_reader_allows_login(
    client,
    test_user,
):
    admin_paths = (
        "/policy/rss/sources/",
        "/policy/rss/sources/new/",
        "/policy/rss/keywords/",
        "/policy/rss/keywords/new/",
        "/policy/rss/logs/",
    )
    client.force_login(test_user)
    assert all(client.get(path).status_code == 403 for path in admin_paths)
    assert client.get("/policy/rss/reader/").status_code == 200

    test_user.is_staff = True
    test_user.save(update_fields=["is_staff"])
    client.force_login(test_user)
    assert all(client.get(path).status_code == 200 for path in admin_paths)


@pytest.mark.django_db
def test_policy_rss_reader_api_is_authenticated_filtered_and_bounded(
    authenticated_client,
):
    source_model = django_apps.get_model("policy", "RSSSourceConfigModel")
    policy_log_model = django_apps.get_model("policy", "PolicyLog")
    source = source_model._default_manager.create(
        name="政策阅读源",
        url="https://example.com/policy.xml",
        category="gov_docs",
        is_active=True,
        fetch_interval_hours=6,
    )
    policy_log_model._default_manager.create(
        event_date=date(2026, 7, 26),
        level="P2",
        title="政策阅读条目",
        description="用于验证 RSS Reader owner API 的政策条目。",
        evidence_url="https://example.com/policy/1",
        info_category="macro",
        rss_source=source,
        audit_status="pending_review",
    )

    response = authenticated_client.get(
        "/api/policy/rss/reader/",
        {
            "source_id": source.id,
            "level": "P2",
            "category": "macro",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["title"] == "政策阅读条目"
    assert response.json()["results"][0]["rss_source_name"] == "政策阅读源"
