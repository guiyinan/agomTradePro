from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.events.interface.serializers import EventPublishRequestSerializer


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="events_user",
        password="testpass123",
        email="events@example.com",
        is_staff=True,
    )


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
def test_events_query_rejects_unknown_and_ambiguous_filters(authenticated_client):
    unknown = authenticated_client.get("/api/events/query/?unexpected=true")
    ambiguous = authenticated_client.get(
        "/api/events/query/?event_type=regime_changed" "&event_types=regime_changed"
    )

    assert unknown.status_code == 400
    assert unknown.json()["error_code"] == "INVALID_QUERY"
    assert ambiguous.status_code == 400
    assert ambiguous.json()["error_code"] == "INVALID_QUERY"


@pytest.mark.django_db
def test_events_query_rejects_inverted_time_window(authenticated_client):
    response = authenticated_client.get(
        "/api/events/query/?since=2026-07-27T00:00:00Z" "&until=2026-07-26T00:00:00Z"
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_QUERY"


@pytest.mark.django_db
def test_events_publish_rejects_unknown_event_type(authenticated_client):
    response = authenticated_client.post(
        "/api/events/publish/",
        {"event_type": "unknown", "payload": {}},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_REQUEST"


def test_events_publish_serializer_rejects_non_finite_json_value():
    serializer = EventPublishRequestSerializer(
        data={
            "event_type": "regime_changed",
            "payload": {"score": float("nan")},
        }
    )

    assert serializer.is_valid() is False
    assert "payload" in serializer.errors


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
    with patch(
        "apps.events.domain.services.get_event_bus", side_effect=RuntimeError("bus exploded")
    ):
        response = authenticated_client.get("/api/events/status/")

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert payload["message"] == "Event bus status is unavailable."
    assert "exploded" not in payload["message"]


@pytest.mark.django_db
def test_events_publish_internal_error_is_redacted(authenticated_client):
    with patch(
        "apps.events.interface.views.PublishEventUseCase",
        side_effect=RuntimeError("secret publication detail"),
    ):
        response = authenticated_client.post(
            "/api/events/publish/",
            {"event_type": "regime_changed", "payload": {}},
            format="json",
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["message"] == "Event publication failed."
    assert "secret" not in payload["message"]


@pytest.mark.django_db
def test_events_query_use_case_failure_is_internal_and_redacted(
    authenticated_client,
):
    use_case = SimpleNamespace(
        execute=lambda request: SimpleNamespace(
            success=False,
            error_message="secret database detail",
        )
    )
    with patch(
        "apps.events.interface.views.QueryEventsUseCase",
        return_value=use_case,
    ):
        response = authenticated_client.get("/api/events/query/")

    assert response.status_code == 500
    payload = response.json()
    assert payload["message"] == "Failed to query events."
    assert "secret" not in payload["message"]
