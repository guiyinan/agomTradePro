"""
Events API Contract Tests

Integration tests for the Events API endpoints.
Tests verify that the Events API endpoints return proper JSON responses
and are not returning 501 placeholder responses.

Phase 3: Events API Migration from placeholder to real implementation.
"""

import json
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.events.application.use_cases import PublishEventUseCase
from apps.events.infrastructure.event_store import (
    DatabaseEventStore,
    StoredEventModel,
)
from apps.events.interface import views as event_views


def _build_authenticated_api_client(
    username: str = "events_api_tester",
    *,
    is_staff: bool = True,
) -> APIClient:
    """Build an authenticated API client for testing."""
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(username=username)
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        user.save(update_fields=["is_staff"])
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

    def test_publish_rejects_unknown_request_fields(self):
        """Publishing must reject fields outside the canonical contract."""
        client = _build_authenticated_api_client("events_publish_unknown_field")

        response = client.post(
            "/api/events/publish/",
            data={
                "event_type": "regime_changed",
                "payload": {"new_regime": "Overheat"},
                "unexpected": True,
            },
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["error_code"] == "INVALID_REQUEST"
        assert StoredEventModel.objects.count() == 0

    def test_duplicate_event_id_does_not_notify_subscribers_twice(self, monkeypatch):
        """Database identity must block duplicate cross-module side effects."""

        class _RecordingEventBus:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

            def get_metrics(self):
                return SimpleNamespace(total_processed=len(self.events))

        event_bus = _RecordingEventBus()
        monkeypatch.setattr(
            event_views,
            "PublishEventUseCase",
            lambda: PublishEventUseCase(
                event_bus=event_bus,
                event_store=DatabaseEventStore(),
            ),
        )
        client = _build_authenticated_api_client("events_publish_duplicate")
        request_payload = {
            "event_type": "regime_changed",
            "payload": {"new_regime": "Overheat"},
            "event_id": "event-idempotency-001",
            "occurred_at": "2026-07-12T12:00:00Z",
        }

        first_response = client.post(
            "/api/events/publish/",
            data=request_payload,
            format="json",
        )
        duplicate_response = client.post(
            "/api/events/publish/",
            data=request_payload,
            format="json",
        )

        assert first_response.status_code == 200
        assert first_response.json()["subscribers_notified"] == 1
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error_code"] == "EVENT_ALREADY_EXISTS"
        assert StoredEventModel.objects.filter(
            event_id="event-idempotency-001"
        ).count() == 1
        assert len(event_bus.events) == 1

    def test_persistence_failure_blocks_event_bus_publication(self, monkeypatch):
        """Subscribers must not run when the event store rejects the append."""

        class _FailingEventStore:
            @staticmethod
            def get_by_id(event_id):
                return None

            @staticmethod
            def append(event):
                return False

        class _RecordingEventBus:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event)

            @staticmethod
            def get_metrics():
                return SimpleNamespace(total_processed=0)

        event_bus = _RecordingEventBus()
        monkeypatch.setattr(
            event_views,
            "PublishEventUseCase",
            lambda: PublishEventUseCase(
                event_bus=event_bus,
                event_store=_FailingEventStore(),
            ),
        )
        client = _build_authenticated_api_client("events_publish_store_failure")

        response = client.post(
            "/api/events/publish/",
            data={
                "event_type": "regime_changed",
                "payload": {"new_regime": "Overheat"},
                "event_id": "event-store-failure-001",
            },
            format="json",
        )

        assert response.status_code == 500
        assert response.json()["error_code"] == "EVENT_PERSISTENCE_FAILED"
        assert event_bus.events == []


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
    """Tests for the controlled replay preview endpoint."""

    @pytest.fixture(autouse=True)
    def _enable_controlled_replay(self, settings: object) -> None:
        setattr(settings, "EVENT_REPLAY_ENABLED", True)

    def test_replay_endpoint_returns_json_not_501(self):
        """
        POST /api/events/replay/preview/ must return JSON, not a placeholder.
        """
        client = _build_authenticated_api_client("events_replay_contract")

        response = client.post(
            "/api/events/replay/preview/",
            data=json.dumps({
                "target_key": "events.decision.approved",
                "event_type": "decision_approved",
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
            "/api/events/replay/preview/",
            data=json.dumps({
                "target_key": "events.decision.approved",
                "event_type": "decision_approved",
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

    def test_non_staff_request_is_denied(self):
        """Arbitrary domain event publication is staff-only."""
        client = _build_authenticated_api_client(
            "events_auth_non_staff",
            is_staff=False,
        )

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {"test": "data"},
            }),
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_staff_request_succeeds(self):
        """Staff users may publish canonical domain events."""
        client = _build_authenticated_api_client("events_auth_staff")

        response = client.post(
            "/api/events/publish/",
            data=json.dumps({
                "event_type": "regime_changed",
                "payload": {"test": "data"},
            }),
            content_type="application/json",
        )

        assert response.status_code == 200

