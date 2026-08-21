"""Pure API and SSE contracts for the future queued Terminal Agent path.

TAR-01 freezes names and response envelopes without adding a route, ORM
adapter, broker publisher, Celery task, or Agent SDK dependency.  TAR-02 and
TAR-03 must implement these contracts rather than inventing a second wire
shape.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalRunContractError,
    TerminalRunStatus,
    assert_no_sensitive_runtime_data,
    validate_terminal_run_id,
)


class TerminalRunApiContractError(TerminalRunContractError):
    """Raised when a queued Terminal Agent wire contract is malformed."""


class TerminalRunApiRoute(StrEnum):
    """Canonical routes reserved for the asynchronous Terminal Agent API."""

    CREATE = "/api/terminal/runs/"
    DETAIL = "/api/terminal/runs/{run_id}/"
    EVENTS = "/api/terminal/runs/{run_id}/events/"
    CANCEL = "/api/terminal/runs/{run_id}/cancel/"
    QUEUE = "/api/terminal/runs/queue/"


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _require_aware(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware API timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRunApiContractError(f"{field_name} must be timezone-aware")
    return value


def _require_non_empty(value: str, field_name: str) -> str:
    """Require a trimmed, non-empty wire identifier or URL."""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise TerminalRunApiContractError(f"{field_name} must be a non-empty string")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    """Require a non-negative integer while rejecting bool-as-int values."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TerminalRunApiContractError(f"{field_name} must be a non-negative integer")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    """Require a positive integer while rejecting bool-as-int values."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TerminalRunApiContractError(f"{field_name} must be a positive integer")
    return value


def _require_status(
    value: TerminalRunStatus,
    allowed: frozenset[TerminalRunStatus],
    field_name: str,
) -> TerminalRunStatus:
    """Require an enum status and constrain it to the response contract."""

    if not isinstance(value, TerminalRunStatus) or value not in allowed:
        raise TerminalRunApiContractError(f"{field_name} has an invalid status")
    return value


def _validate_json_value(value: object, path: str) -> None:
    """Validate finite JSON-compatible event data without coercing it."""

    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TerminalRunApiContractError(f"{path} must contain finite numbers")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise TerminalRunApiContractError(f"{path} contains a non-string key")
            _validate_json_value(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{path}[{index}]")
        return
    raise TerminalRunApiContractError(f"{path} contains a non-JSON value")


def terminal_run_route(route: TerminalRunApiRoute, run_id: str | None = None) -> str:
    """Render one canonical route and reject accidental path substitution."""

    if not isinstance(route, TerminalRunApiRoute):
        raise TerminalRunApiContractError("route must be TerminalRunApiRoute")
    has_run_placeholder = "{run_id}" in route.value
    if has_run_placeholder:
        if run_id is None:
            raise TerminalRunApiContractError("run_id is required for this route")
        try:
            validated_run_id = validate_terminal_run_id(run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        return route.value.replace("{run_id}", validated_run_id)
    if run_id is not None:
        raise TerminalRunApiContractError("run_id is not accepted for this route")
    return route.value


@dataclass(frozen=True, slots=True)
class TerminalRunAcceptedResponse:
    """Stable `202 Accepted` response for a newly admitted run."""

    run_id: str
    task_id: int
    status: TerminalRunStatus
    submitted_at: datetime
    status_url: str
    events_url: str
    cancel_url: str

    def __post_init__(self) -> None:
        """Validate the minimum response returned by the create endpoint."""

        try:
            validate_terminal_run_id(self.run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        if isinstance(self.task_id, bool) or not isinstance(self.task_id, int) or self.task_id <= 0:
            raise TerminalRunApiContractError("task_id must be a positive integer")
        _require_status(
            self.status,
            frozenset({TerminalRunStatus.ACCEPTED, TerminalRunStatus.QUEUED}),
            "accepted response",
        )
        _require_aware(self.submitted_at, "submitted_at")
        expected_urls = (
            terminal_run_route(TerminalRunApiRoute.DETAIL, self.run_id),
            terminal_run_route(TerminalRunApiRoute.EVENTS, self.run_id),
            terminal_run_route(TerminalRunApiRoute.CANCEL, self.run_id),
        )
        if (self.status_url, self.events_url, self.cancel_url) != expected_urls:
            raise TerminalRunApiContractError(
                "accepted response URLs do not match canonical routes"
            )

    def to_payload(self) -> dict[str, int | str]:
        """Return the exact public create response without prompt or credentials."""

        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "submitted_at": self.submitted_at.isoformat(),
            "status_url": self.status_url,
            "events_url": self.events_url,
            "cancel_url": self.cancel_url,
        }


@dataclass(frozen=True, slots=True)
class TerminalRunStatusResponse:
    """Owner-scoped status response for polling or SSE recovery."""

    run_id: str
    status: TerminalRunStatus
    updated_at: datetime
    status_url: str
    events_url: str
    cancel_url: str
    error_code: str | None = None
    result_ref: str | None = None

    def __post_init__(self) -> None:
        """Validate status timestamps, URLs, and stable optional fields."""

        try:
            validate_terminal_run_id(self.run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        _require_status(self.status, frozenset(TerminalRunStatus), "status response")
        _require_aware(self.updated_at, "updated_at")
        expected_urls = (
            terminal_run_route(TerminalRunApiRoute.DETAIL, self.run_id),
            terminal_run_route(TerminalRunApiRoute.EVENTS, self.run_id),
            terminal_run_route(TerminalRunApiRoute.CANCEL, self.run_id),
        )
        if (self.status_url, self.events_url, self.cancel_url) != expected_urls:
            raise TerminalRunApiContractError("status response URLs do not match canonical routes")
        if self.error_code is not None:
            _require_non_empty(self.error_code, "error_code")
        if self.result_ref is not None:
            _require_non_empty(self.result_ref, "result_ref")

    def to_payload(self) -> dict[str, int | str | None]:
        """Return the stable status payload with no queue internals or secrets."""

        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "updated_at": self.updated_at.isoformat(),
            "status_url": self.status_url,
            "events_url": self.events_url,
            "cancel_url": self.cancel_url,
            "error_code": self.error_code,
            "result_ref": self.result_ref,
        }


@dataclass(frozen=True, slots=True)
class TerminalRunCancelResponse:
    """Idempotent cancellation response for a run owner."""

    run_id: str
    status: TerminalRunStatus
    cancel_requested_at: datetime | None

    def __post_init__(self) -> None:
        """Validate cancellation status and optional timestamp."""

        try:
            validate_terminal_run_id(self.run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        _require_status(
            self.status,
            frozenset({TerminalRunStatus.CANCEL_REQUESTED, TerminalRunStatus.CANCELLED}),
            "cancel response",
        )
        if self.cancel_requested_at is not None:
            _require_aware(self.cancel_requested_at, "cancel_requested_at")

    def to_payload(self) -> dict[str, str | None]:
        """Return the stable cancellation response."""

        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "cancel_requested_at": (
                self.cancel_requested_at.isoformat() if self.cancel_requested_at else None
            ),
        }


@dataclass(frozen=True, slots=True)
class TerminalRunEvent:
    """Replayable SSE event envelope with safe JSON data only."""

    event_id: str
    event_type: str
    run_id: str
    occurred_at: datetime
    data: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        """Validate event identity, timestamp, and redacted data boundary."""

        _require_non_empty(self.event_id, "event_id")
        _require_non_empty(self.event_type, "event_type")
        try:
            validate_terminal_run_id(self.run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        _require_aware(self.occurred_at, "occurred_at")
        _validate_json_value(self.data, "data")
        try:
            assert_no_sensitive_runtime_data(self.data)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc

    def to_payload(self) -> dict[str, object]:
        """Return one SSE-compatible event envelope."""

        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "occurred_at": self.occurred_at.isoformat(),
            "data": dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class TerminalRunEventReplayQuery:
    """Owner-scoped, bounded cursor used to request an event replay."""

    run_id: str
    actor_user_id: int
    after_sequence: int = 0
    limit: int = 100

    def __post_init__(self) -> None:
        """Validate the identity and bounded replay controls."""

        try:
            validate_terminal_run_id(self.run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        _require_positive_int(self.actor_user_id, "actor_user_id")
        _require_non_negative_int(self.after_sequence, "after_sequence")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TerminalRunApiContractError("limit must be a positive integer")
        if self.limit <= 0 or self.limit > 100:
            raise TerminalRunApiContractError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class TerminalRunEventReplay:
    """One sequenced event that is safe to replay after a cursor."""

    event_id: str
    event_type: str
    run_id: str
    occurred_at: datetime
    sequence: int
    data: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        """Validate event identity, sequence, clock and redacted data."""

        _require_non_empty(self.event_id, "event_id")
        _require_non_empty(self.event_type, "event_type")
        try:
            validate_terminal_run_id(self.run_id)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc
        _require_aware(self.occurred_at, "occurred_at")
        _require_positive_int(self.sequence, "sequence")
        _validate_json_value(self.data, "data")
        try:
            assert_no_sensitive_runtime_data(self.data)
        except TerminalRunContractError as exc:
            raise TerminalRunApiContractError(str(exc)) from exc

    def to_payload(self) -> dict[str, object]:
        """Return the complete public replay envelope."""

        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "occurred_at": self.occurred_at.isoformat(),
            "sequence": self.sequence,
            "data": dict(self.data),
        }


def validate_terminal_run_event_replay(
    query: TerminalRunEventReplayQuery,
    events: Sequence[TerminalRunEventReplay],
) -> tuple[TerminalRunEventReplay, ...]:
    """Validate one bounded, owner-scoped, strictly ordered replay batch.

    The validator deliberately does not discard events after a terminal status:
    a reconnecting owner must be able to recover the complete durable history.
    Repository implementations still have to enforce ``query.actor_user_id``
    against the run owner before constructing this batch.
    """

    if not isinstance(query, TerminalRunEventReplayQuery):
        raise TerminalRunApiContractError("query must be TerminalRunEventReplayQuery")
    if len(events) > query.limit:
        raise TerminalRunApiContractError("event replay exceeds the requested limit")

    previous_sequence = query.after_sequence
    seen_event_ids: set[str] = set()
    validated: list[TerminalRunEventReplay] = []
    for event in events:
        if not isinstance(event, TerminalRunEventReplay):
            raise TerminalRunApiContractError("event replay contains an invalid event")
        if event.run_id != query.run_id:
            raise TerminalRunApiContractError("event replay run_id does not match query")
        if event.sequence <= previous_sequence:
            raise TerminalRunApiContractError("event replay sequence is not strictly increasing")
        if event.event_id in seen_event_ids:
            raise TerminalRunApiContractError("event replay contains a duplicate event_id")
        seen_event_ids.add(event.event_id)
        previous_sequence = event.sequence
        validated.append(event)
    return tuple(validated)
