"""Staff-only controlled event replay API contracts."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.events.application.replay_service import (
    ReplayConflictError,
    ReplayDisabledError,
)


@pytest.fixture
def replay_users(db):
    model = get_user_model()
    return (
        model.objects.create_user(username="replay-user"),
        model.objects.create_user(username="replay-staff", is_staff=True),
    )


@pytest.mark.django_db
def test_replay_api_requires_staff(replay_users) -> None:
    user, staff = replay_users
    client = APIClient()
    payload = {
        "target_key": "events.decision.approved",
        "event_type": "decision_approved",
    }

    assert client.post("/api/events/replay/preview/", payload, format="json").status_code == 403
    client.force_authenticate(user=user)
    assert client.post("/api/events/replay/preview/", payload, format="json").status_code == 403
    client.force_authenticate(user=staff)


@pytest.mark.django_db
def test_replay_preview_is_strict_and_does_not_commit(
    replay_users,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, staff = replay_users
    calls = []

    class _Service:
        @staticmethod
        def preview(target_key, replay_filter):
            calls.append((target_key, replay_filter.event_type.value))
            return {"target_key": target_key, "candidate_count": 2}

        @staticmethod
        def commit(*args, **kwargs):
            raise AssertionError("preview must not commit")

    monkeypatch.setattr(
        "apps.events.interface.views.build_replay_service",
        lambda: _Service(),
    )
    client = APIClient()
    client.force_authenticate(user=staff)
    url = "/api/events/replay/preview/"

    invalid = client.post(
        url,
        {
            "target_key": "events.decision.approved",
            "event_type": "decision_approved",
            "target_handler_class": "arbitrary.Handler",
        },
        format="json",
    )
    response = client.post(
        url,
        {
            "target_key": "events.decision.approved",
            "event_type": "decision_approved",
            "limit": 10,
        },
        format="json",
    )

    assert invalid.status_code == 400
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["candidate_count"] == 2
    assert calls == [("events.decision.approved", "decision_approved")]


@pytest.mark.django_db
def test_replay_commit_returns_partial_and_maps_operational_errors(
    replay_users,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, staff = replay_users
    client = APIClient()
    client.force_authenticate(user=staff)
    url = "/api/events/replay/commit/"
    payload = {
        "target_key": "events.decision.approved",
        "event_type": "decision_approved",
        "idempotency_key": "idem-1",
    }
    service = SimpleNamespace(
        commit=lambda *args, **kwargs: {
            "outcome": "partial",
            "attempted": 2,
            "succeeded": 1,
            "skipped": 0,
            "failed": 1,
            "failures": [{"event_id": "2"}],
        }
    )
    monkeypatch.setattr(
        "apps.events.interface.views.build_replay_service", lambda: service
    )

    partial = client.post(url, payload, format="json")
    assert partial.status_code == 200
    assert partial.json()["success"] is False
    assert partial.json()["outcome"] == "partial"

    service.commit = lambda *args, **kwargs: (_ for _ in ()).throw(
        ReplayConflictError("conflict")
    )
    assert client.post(url, payload, format="json").status_code == 409
    service.commit = lambda *args, **kwargs: (_ for _ in ()).throw(
        ReplayDisabledError("disabled")
    )
    assert client.post(url, payload, format="json").status_code == 503
