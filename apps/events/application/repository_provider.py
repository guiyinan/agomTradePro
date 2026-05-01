"""Composition helpers for events application consumers."""

from __future__ import annotations

from apps.events.infrastructure.celery_event_bus import (
    CeleryEventBus,
    is_celery_available,
)
from apps.events.infrastructure.event_store import (
    DatabaseEventStore,
    EventReplayHandler,
    InMemoryEventStore,
    SnapshotStore,
    get_event_store,
    get_replay_handler,
    get_snapshot_store,
)
from apps.events.infrastructure.providers import (
    get_alpha_candidate_repository,
    get_decision_execution_sync_repository,
    get_decision_request_repository,
    get_failed_event_repository,
)

__all__ = [
    "CeleryEventBus",
    "DatabaseEventStore",
    "EventReplayHandler",
    "InMemoryEventStore",
    "SnapshotStore",
    "get_alpha_candidate_repository",
    "get_decision_execution_sync_repository",
    "get_decision_request_repository",
    "get_event_store",
    "get_failed_event_repository",
    "get_replay_handler",
    "get_snapshot_store",
    "is_celery_available",
]
