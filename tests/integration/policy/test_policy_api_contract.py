import json
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.policy.infrastructure.models import PolicyLog
from apps.policy.interface import event_api_views


@pytest.fixture(autouse=True)
def _use_locmem_cache(settings):
    """
    Force local in-memory cache for this module's API contract tests.

    These tests exercise DRF throttling paths. In CI/local environments without
    Redis, default cache backend may raise connection errors and hide real API
    contract regressions.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "policy-api-contract-tests",
        }
    }


def _build_authenticated_api_client(
    username: str = "policy_api_tester",
    *,
    is_staff: bool = False,
) -> APIClient:
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(username=username)
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        user.save(update_fields=["is_staff"])
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_api_policy_events_endpoint_returns_json_contract():
    """
    /api/policy/events/ must be API endpoint (JSON), not HTML page route.
    """
    client = _build_authenticated_api_client("policy_api_contract")
    response = client.get("/api/policy/events/")

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
    assert "error" in response.json()


@pytest.mark.django_db
def test_policy_event_queries_reject_unknown_and_reversed_ranges():
    client = _build_authenticated_api_client("policy_api_strict_query")

    unknown = client.get("/api/policy/events/?start_date=2026-07-01&end_date=2026-07-10&typo=1")
    reversed_range = client.get("/api/policy/events/?start_date=2026-07-10&end_date=2026-07-01")

    assert unknown.status_code == 400
    assert reversed_range.status_code == 400
    assert unknown.json()["error"] == "Invalid query parameters"


@pytest.mark.django_db
def test_policy_event_identity_rejects_non_positive_id():
    client = _build_authenticated_api_client(
        "policy_api_invalid_identity",
        is_staff=True,
    )

    response = client.delete("/api/policy/events/2026-07-10/?event_id=0")

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid request parameters"


@pytest.mark.django_db
def test_policy_event_create_does_not_expose_internal_exception(monkeypatch):
    client = _build_authenticated_api_client(
        "policy_api_stable_error",
        is_staff=True,
    )

    def fail_repository():
        raise RuntimeError("database-password")

    monkeypatch.setattr(
        event_api_views,
        "get_current_policy_repository",
        fail_repository,
    )
    response = client.post(
        "/api/policy/events/",
        {
            "event_date": "2026-07-11",
            "level": "P0",
            "title": "Stable error contract",
            "description": "Internal details must remain private.",
            "evidence_url": "https://example.com/policy/error",
        },
        format="json",
    )

    assert response.status_code == 500
    assert response.json()["errors"] == ["Internal server error"]
    assert "database-password" not in response.content.decode()


@pytest.mark.django_db
def test_api_policy_events_returns_canonical_history_envelope():
    client = _build_authenticated_api_client("policy_api_history_contract")
    event_date = date(2026, 7, 9)
    PolicyLog._default_manager.create(
        event_date=event_date,
        level="P2",
        title="Liquidity support",
        description="Targeted liquidity support was announced with sufficient detail.",
        evidence_url="https://example.com/policy/history",
    )

    response = client.get("/api/policy/events/?start_date=2026-07-01&end_date=2026-07-10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["start_date"] == "2026-07-01"
    assert payload["end_date"] == "2026-07-10"
    assert payload["events"][0]["level"] == "P2"
    assert payload["events"][0]["title"] == "Liquidity support"
    assert payload["level_stats"]["by_level"]["P2"]["count"] == 1


@pytest.mark.django_db
def test_api_policy_events_does_not_fail_on_legacy_invalid_evidence_url():
    client = _build_authenticated_api_client("policy_api_legacy_url")
    PolicyLog._default_manager.create(
        event_date=date(2026, 6, 2),
        level="P1",
        title="Legacy imported event",
        description="Legacy data remains readable while new writes stay strictly validated.",
        evidence_url="legacy-source-without-scheme",
    )

    response = client.get("/api/policy/events/?start_date=2026-06-02&end_date=2026-06-02")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["events"][0]["evidence_url"] == "legacy-source-without-scheme"


@pytest.mark.django_db
def test_create_policy_event_requires_staff():
    client = _build_authenticated_api_client("policy_api_create_forbidden")

    response = client.post(
        "/api/policy/events/",
        {
            "event_date": "2026-07-11",
            "level": "P0",
            "title": "Restricted policy event",
            "description": "A regular authenticated user must not create policy events.",
            "evidence_url": "https://example.com/policy/restricted",
        },
        format="json",
    )

    assert response.status_code == 403
    assert PolicyLog._default_manager.filter(title="Restricted policy event").exists() is False


@pytest.mark.django_db
def test_staff_can_create_policy_event_through_canonical_contract():
    client = _build_authenticated_api_client(
        "policy_api_create_staff",
        is_staff=True,
    )

    response = client.post(
        "/api/policy/events/",
        {
            "event_date": "2026-07-11",
            "level": "P0",
            "title": "Governed policy event",
            "description": "A staff user creates a policy event through the canonical API.",
            "evidence_url": "https://example.com/policy/governed",
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["event"]["title"] == "Governed policy event"
    assert PolicyLog._default_manager.filter(
        event_date=date(2026, 7, 11),
        title="Governed policy event",
        level="P0",
    ).exists()


@pytest.mark.django_db
def test_delete_policy_event_by_id_only_deletes_target_event():
    """
    DELETE with event_id should only delete one target event on same day.
    """
    client = _build_authenticated_api_client("policy_api_delete", is_staff=True)
    event_date = date(2026, 2, 1)
    keep = PolicyLog._default_manager.create(
        event_date=event_date,
        level="P1",
        title="Event Keep",
        description="Description for event keep with enough length.",
        evidence_url="https://example.com/keep",
    )
    delete_target = PolicyLog._default_manager.create(
        event_date=event_date,
        level="P2",
        title="Event Delete",
        description="Description for event delete with enough length.",
        evidence_url="https://example.com/delete",
    )

    response = client.delete(
        f"/api/policy/events/{event_date.isoformat()}/?event_id={delete_target.id}"
    )

    assert response.status_code == 204
    assert PolicyLog._default_manager.filter(id=delete_target.id).exists() is False
    assert PolicyLog._default_manager.filter(id=keep.id).exists() is True


@pytest.mark.django_db
def test_update_policy_event_by_id_only_updates_target_event():
    """
    PUT with event_id should update target event only, even on same day.
    """
    client = _build_authenticated_api_client("policy_api_update", is_staff=True)
    event_date = date(2026, 2, 2)
    target = PolicyLog._default_manager.create(
        event_date=event_date,
        level="P1",
        title="Target Event",
        description="Description for target event with enough length.",
        evidence_url="https://example.com/target",
    )
    untouched = PolicyLog._default_manager.create(
        event_date=event_date,
        level="P2",
        title="Untouched Event",
        description="Description for untouched event with enough length.",
        evidence_url="https://example.com/untouched",
    )

    response = client.put(
        f"/api/policy/events/{event_date.isoformat()}/?event_id={target.id}",
        data=json.dumps(
            {
                "event_date": event_date.isoformat(),
                "level": "P3",
                "title": "Target Event Updated",
                "description": "Updated description for target event with enough length.",
                "evidence_url": "https://example.com/target-updated",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    target.refresh_from_db()
    untouched.refresh_from_db()
    assert target.title == "Target Event Updated"
    assert target.level == "P3"
    assert untouched.title == "Untouched Event"
    assert untouched.level == "P2"
