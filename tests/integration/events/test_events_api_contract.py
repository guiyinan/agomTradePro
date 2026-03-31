"""
Events API Contract Tests

Integration tests for the Events API endpoints.
Tests verify that the Events API endpoints return proper JSON responses
and are not returning 501 placeholder responses.

Phase 3: Events API Migration from placeholder to real implementation.
"""

import json
from datetime import datetime
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.events.domain.entities import EventType, create_event
from apps.events.domain.services import get_event_bus
from apps.events.infrastructure.event_store import get_event_store


def _build_authenticated_api_client(username: str = "events_api_tester") -> APIClient:
    """Build an authenticated API client for testing."""
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(username=username)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestEventsPublishAPI:
    """Tests for /api/events/publish/ endpoint."""

    def test_publish_endpoint_returns_json_not_501(self):
        """
        POST /api/events/publish/ must return JSON response, not 501 placeholder.
        """
        client = _build_authenticated_api_client("events_publish_contract")

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {"old_regime": "Recovery", "new_regime": "Overheat"},
                "metadata": {"source": "test"},
            }),
            content_type="application/json",
        )

        # Should NOT return 501
        assert response.status_code != 501, "Events API should not return 501 placeholder"
        # Should return JSON
        assert response.headers["Content-Type"].startswith("application/json")
        # Should have success response structure
        data = response.json()
        assert "success" in data
        assert "event_id" in data
        assert "timestamp" in data

    def test_publish_with_valid_event_type_succeeds(self):
        """Publishing a valid event should succeed."""
        client = _build_authenticated_api_client("events_publish_valid")

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {"new_regime": "Overheat"},
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "event_id" in data
        assert "published_at" in data

    def test_publish_with_invalid_event_type_fails_gracefully(self):
        """Publishing with invalid event_type should return validation error."""
        client = _build_authenticated_api_client("events_publish_invalid")

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "invalid_event_type",
                "payload": {},
            }),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False


@pytest.mark.django_db
class TestEventsQueryAPI:
    """Tests for /api/events/query/ endpoint."""

    def test_query_endpoint_returns_json_not_501(self):
        """
        GET /api/events/query/ must return JSON response, not 501 placeholder.
        """
        client = _build_authenticated_api_client("events_query_contract")

        response = client.get("/api/events/query/")

        # Should NOT return 501
        assert response.status_code != 501, "Events query API should not return 501 placeholder"
        # Should return JSON
        assert response.headers["Content-Type"].startswith("application/json")
        # Should have success response structure
        data = response.json()
        assert "success" in data
        assert "events" in data
        assert "total_count" in data

    def test_query_with_event_type_filter(self):
        """Query with event_type filter should work."""
        client = _build_authenticated_api_client("events_query_filter")

        # First publish an event
        publish_response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {"new_regime": "Overheat"},
            }),
            content_type="application/json",
        )
        # Make sure publish succeeded
        assert publish_response.status_code == 200

        # Then query for it
        response = client.get("/api/events/query/?event_type=regime_changed&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_query_with_limit_parameter(self):
        """Query with limit parameter should respect the limit."""
        client = _build_authenticated_api_client("events_query_limit")

        response = client.get("/api/events/query/?limit=5")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return at most 5 events
        assert len(data["events"]) <= 5


@pytest.mark.django_db
class TestEventsMetricsAPI:
    """Tests for /api/events/metrics/ endpoint."""

    def test_metrics_endpoint_returns_json_not_501(self):
        """
        GET /api/events/metrics/ must return JSON response, not 501 placeholder.
        """
        client = _build_authenticated_api_client("events_metrics_contract")

        response = client.get("/api/events/metrics/")

        # Should NOT return 501
        assert response.status_code != 501, "Events metrics API should not return 501 placeholder"
        # Should return JSON
        assert response.headers["Content-Type"].startswith("application/json")
        # Should have success response structure
        data = response.json()
        assert "success" in data
        assert "metrics" in data
        assert "events_by_type" in data

    def test_metrics_returns_valid_metrics_structure(self):
        """Metrics endpoint should return valid metrics data."""
        client = _build_authenticated_api_client("events_metrics_structure")

        response = client.get("/api/events/metrics/")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        metrics = data["metrics"]
        assert "total_published" in metrics
        assert "total_processed" in metrics
        assert "total_failed" in metrics
        assert "total_subscribers" in metrics
        assert "avg_processing_time_ms" in metrics


@pytest.mark.django_db
class TestEventsStatusAPI:
    """Tests for /api/events/status/ endpoint."""

    def test_status_endpoint_returns_json_not_501(self):
        """
        GET /api/events/status/ must return JSON response, not 501 placeholder.
        """
        client = _build_authenticated_api_client("events_status_contract")

        response = client.get("/api/events/status/")

        # Should NOT return 501
        assert response.status_code != 501, "Events status API should not return 501 placeholder"
        # Should return JSON
        assert response.headers["Content-Type"].startswith("application/json")
        # Should have success response structure
        data = response.json()
        assert "success" in data
        assert "is_running" in data

    def test_status_returns_event_bus_state(self):
        """Status endpoint should return event bus state."""
        client = _build_authenticated_api_client("events_status_state")

        response = client.get("/api/events/status/")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "is_running" in data
        assert "total_subscribers" in data
        assert "queue_size" in data
        assert isinstance(data["is_running"], bool)


@pytest.mark.django_db
class TestEventsReplayAPI:
    """Tests for /api/events/replay/ endpoint."""

    def test_replay_endpoint_returns_json_not_501(self):
        """
        POST /api/events/replay/ must return JSON response, not 501 placeholder.
        """
        client = _build_authenticated_api_client("events_replay_contract")

        response = client.post(
            "/api/events/replay/",
            data=json.dumps({
                "limit": 10,
            }),
            content_type="application/json",
        )

        # Should NOT return 501
        assert response.status_code != 501, "Events replay API should not return 501 placeholder"
        # Should return JSON
        assert response.headers["Content-Type"].startswith("application/json")
        # Should have success response structure
        data = response.json()
        assert "success" in data

    def test_replay_with_limit_parameter(self):
        """Replay with limit parameter should work."""
        client = _build_authenticated_api_client("events_replay_limit")

        response = client.post(
            "/api/events/replay/",
            data=json.dumps({
                "limit": 5,
            }),
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        # Even if no events to replay, should return success
        assert isinstance(data["success"], bool)


@pytest.mark.django_db
class TestEventsLegacyRoutesRemoved:
    """Historical page-style event routes should stay removed before release."""

    def test_old_event_routes_return_404(self):
        client = _build_authenticated_api_client("events_legacy_routes_removed")

        for path in [
            "/events/publish/",
            "/events/query/",
            "/events/metrics/",
            "/events/status/",
            "/events/replay/",
        ]:
            response = client.get(path, follow=False)
            assert response.status_code == 404


@pytest.mark.django_db
class TestEventsAPIAuthentication:
    """Tests for Events API authentication."""

    def test_unauthenticated_request_is_denied(self):
        """Unauthenticated requests should be denied."""
        client = APIClient()  # Not authenticated

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {},
            }),
            content_type="application/json",
        )

        # Should return 401 or 403 for unauthenticated
        assert response.status_code in [401, 403]

    def test_authenticated_request_succeeds(self):
        """Authenticated requests should succeed."""
        client = _build_authenticated_api_client("events_auth_success")

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {"test": "data"},
            }),
            content_type="application/json",
        )

        # Should not be authentication error
        assert response.status_code not in [401, 403]

