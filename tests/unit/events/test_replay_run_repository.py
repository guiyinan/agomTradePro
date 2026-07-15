"""Durable controlled-replay idempotency repository contracts."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.events.infrastructure.repositories import DjangoReplayRunRepository


@pytest.mark.django_db
def test_replay_run_reservation_replay_conflict_and_in_progress() -> None:
    user = get_user_model().objects.create_user(username="replay-owner")
    repository = DjangoReplayRunRepository()
    request = {"event_type": "decision_approved", "limit": 10}

    reserved = repository.reserve(
        requester_id=user.id,
        target_key="events.decision.approved",
        normalized_request=request,
        request_fingerprint="a" * 64,
        idempotency_key="idem-1",
    )
    in_progress = repository.reserve(
        requester_id=user.id,
        target_key="events.decision.approved",
        normalized_request=request,
        request_fingerprint="a" * 64,
        idempotency_key="idem-1",
    )
    conflict = repository.reserve(
        requester_id=user.id,
        target_key="events.decision.approved",
        normalized_request={**request, "limit": 11},
        request_fingerprint="b" * 64,
        idempotency_key="idem-1",
    )

    assert reserved.state == "reserved"
    assert in_progress.state == "in_progress"
    assert conflict.state == "conflict"

    repository.complete(
        reserved.run_id,
        {
            "outcome": "partial",
            "attempted": 2,
            "succeeded": 1,
            "skipped": 0,
            "failed": 1,
            "failures": [{"event_id": "2", "message": "safe"}],
            "results": [],
        },
    )
    replay = repository.reserve(
        requester_id=user.id,
        target_key="events.decision.approved",
        normalized_request=request,
        request_fingerprint="a" * 64,
        idempotency_key="idem-1",
    )

    assert replay.state == "replay"
    assert replay.stored_result["outcome"] == "partial"
    model = repository.model.objects.get(pk=reserved.run_id)
    assert timezone.is_aware(model.started_at)
    assert timezone.is_aware(model.finished_at)
    assert model.failed == 1
