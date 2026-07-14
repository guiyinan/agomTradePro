from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="events_user",
        password="testpass123",
        email="events@example.com",
        is_staff=True,
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_events_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/events/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["publish"] == "/api/events/publish/"
    assert payload["endpoints"]["replay_preview"] == "/api/events/replay/preview/"
    assert payload["endpoints"]["replay_commit"] == "/api/events/replay/commit/"


@pytest.mark.django_db
def test_events_query_rejects_out_of_range_limit(authenticated_client):
    response = authenticated_client.get("/api/events/query/?limit=0")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "INVALID_QUERY"


@pytest.mark.django_db
def test_events_query_rejects_invalid_since_datetime(authenticated_client):
    response = authenticated_client.get("/api/events/query/?since=not-a-datetime")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "INVALID_QUERY"


@pytest.mark.django_db
def test_events_replay_rejects_out_of_range_limit(authenticated_client):
    response = authenticated_client.post(
        "/api/events/replay/preview/",
        {
            "target_key": "events.decision.approved",
            "event_type": "decision_approved",
            "limit": 1001,
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"limit"}


@pytest.mark.django_db
def test_events_replay_rejects_invalid_event_type(authenticated_client):
    response = authenticated_client.post(
        "/api/events/replay/preview/",
        {
            "target_key": "events.decision.approved",
            "event_type": "not-real",
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"event_type"}


@pytest.mark.django_db
def test_events_status_returns_500_when_event_bus_lookup_fails(authenticated_client):
    with patch("apps.events.domain.services.get_event_bus", side_effect=RuntimeError("bus exploded")):
        response = authenticated_client.get("/api/events/status/")

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert payload["message"] == "bus exploded"
