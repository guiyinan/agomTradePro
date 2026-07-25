"""Celery event transport contract regressions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.events.application import tasks as event_tasks
from apps.events.domain.entities import EventType, create_event
from apps.events.infrastructure.celery_event_bus import CeleryEventBus


def test_celery_transport_reads_trace_ids_from_event_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        event_tasks.publish_event_async,
        "delay",
        lambda **kwargs: captured.append(kwargs),
    )
    event = create_event(
        EventType.REGIME_CHANGED,
        {"new_regime": "Recovery"},
        metadata={
            "correlation_id": "correlation-1",
            "causation_id": "causation-1",
        },
        event_id="event-celery-001",
        occurred_at=datetime(2026, 7, 25, 4, 0, tzinfo=UTC),
    )

    event_bus = CeleryEventBus()
    event_bus.publish_async(event)

    assert captured == [
        {
            "event_type": "regime_changed",
            "payload": {"new_regime": "Recovery"},
            "metadata": {
                "correlation_id": "correlation-1",
                "causation_id": "causation-1",
            },
            "event_id": "event-celery-001",
            "occurred_at": "2026-07-25T04:00:00+00:00",
            "correlation_id": "correlation-1",
            "causation_id": "causation-1",
        }
    ]
    event_bus.stop()
