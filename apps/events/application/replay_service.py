"""Preview-first, idempotent orchestration for controlled event replay."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from apps.events.application.replay_registry import ReplayTargetRegistry
from apps.events.domain.entities import DomainEvent, EventType
from apps.events.domain.replay import (
    ReplayEventResult,
    ReplayFilter,
    ReplayRunReservation,
    ReplaySummary,
    replay_fingerprint,
)


class ReplayDisabledError(RuntimeError):
    """Raised when the controlled replay feature flag is disabled."""


class ReplayConflictError(RuntimeError):
    """Raised when an idempotency key is reused for different arguments."""


class ReplayInProgressError(RuntimeError):
    """Raised when an identical replay is already executing."""


class EventStoreProtocol(Protocol):
    """Read boundary required by controlled replay."""

    def get_events(
        self,
        event_type: EventType | None = None,
        event_types: list[EventType] | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
        """Return bounded stored events matching the supplied filters."""


class ReplayRunRepositoryProtocol(Protocol):
    """Durable reservation boundary required by controlled replay."""

    def reserve(
        self,
        *,
        requester_id: int,
        target_key: str,
        normalized_request: dict[str, Any],
        request_fingerprint: str,
        idempotency_key: str,
    ) -> ReplayRunReservation:
        """Atomically reserve or resolve an idempotent replay run."""

    def complete(self, run_id: int, result: dict[str, Any]) -> None:
        """Persist a terminal business result."""

    def fail(self, run_id: int, message: str) -> None:
        """Persist an infrastructure-fatal result."""


class ReplayService:
    """Validate targets, preview candidates, and execute replay exactly once."""

    def __init__(
        self,
        registry: ReplayTargetRegistry,
        event_store: EventStoreProtocol,
        run_repository: ReplayRunRepositoryProtocol,
        *,
        enabled: bool,
    ) -> None:
        self.registry = registry
        self.event_store = event_store
        self.run_repository = run_repository
        self.enabled = enabled

    def preview(
        self,
        target_key: str,
        replay_filter: ReplayFilter,
    ) -> dict[str, Any]:
        """Return candidate metadata without invoking a handler or writing audit state."""

        self._require_enabled()
        target = self.registry.resolve_for_event(target_key, replay_filter.event_type)
        events = self._events(replay_filter)
        return {
            "target_key": target.key,
            "supported_event_types": [
                item.value for item in target.supported_event_types
            ],
            "filter": replay_filter.normalized(),
            "candidate_count": len(events),
            "expected_skip_count": 0,
            "event_sample": [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "occurred_at": event.occurred_at.isoformat(),
                }
                for event in events[:20]
            ],
            "side_effect_description": target.side_effect_description,
        }

    def commit(
        self,
        target_key: str,
        replay_filter: ReplayFilter,
        *,
        requester_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Execute one reserved replay and persist every candidate outcome."""

        self._require_enabled()
        if not str(idempotency_key or "").strip():
            raise ValueError("idempotency_key is required.")
        target = self.registry.resolve_for_event(target_key, replay_filter.event_type)
        normalized_request = replay_filter.normalized()
        fingerprint = replay_fingerprint(target.key, replay_filter)
        reservation = self.run_repository.reserve(
            requester_id=requester_id,
            target_key=target.key,
            normalized_request=normalized_request,
            request_fingerprint=fingerprint,
            idempotency_key=idempotency_key.strip(),
        )
        if reservation.state == "conflict":
            raise ReplayConflictError("Idempotency key conflicts with another replay.")
        if reservation.state == "in_progress":
            raise ReplayInProgressError("An identical replay is already in progress.")
        if reservation.state == "replay":
            return {
                **dict(reservation.stored_result or {}),
                "idempotent_replay": True,
                "run_id": reservation.run_id,
            }

        try:
            handler = target.factory()
            events = self._events(replay_filter)
            results: list[ReplayEventResult] = []
            for event in events:
                if not handler.can_handle(event.event_type):
                    results.append(ReplayEventResult(event.event_id, "skipped"))
                    continue
                try:
                    handler.handle(event)
                    results.append(ReplayEventResult(event.event_id, "succeeded"))
                except Exception:
                    results.append(
                        ReplayEventResult(
                            event.event_id,
                            "failed",
                            "handler_error",
                            "The approved replay handler failed for this event.",
                        )
                    )
            result = {
                **ReplaySummary.from_results(results).to_dict(),
                "run_id": reservation.run_id,
                "idempotent_replay": False,
            }
            self.run_repository.complete(reservation.run_id, result)
            return result
        except Exception as exc:
            self.run_repository.fail(reservation.run_id, str(exc))
            raise

    def _events(self, replay_filter: ReplayFilter) -> list[DomainEvent]:
        events = self.event_store.get_events(
            event_type=replay_filter.event_type,
            since=replay_filter.start_at,
            until=replay_filter.end_at,
            limit=replay_filter.limit,
        )
        return sorted(events, key=lambda event: (event.occurred_at, event.event_id))

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ReplayDisabledError("Controlled event replay is disabled.")
