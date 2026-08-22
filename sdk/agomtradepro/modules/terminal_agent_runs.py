"""Client facade for the durable queued Terminal Agent run API."""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from typing import Any

from ..exceptions import TimeoutError as SDKTimeoutError
from .base import BaseModule

_TERMINAL_RUN_STATUSES = frozenset({"cancelled", "completed", "failed", "timed_out", "orphaned"})


class TerminalAgentRunsModule(BaseModule):
    """Create, inspect, replay, and cancel owner-scoped queued runs."""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/terminal/runs")

    def create_run(
        self,
        *,
        task_id: int,
        client_request_id: str,
        message: str,
        request_digest: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit one durable queued run using only the public run payload."""

        payload: dict[str, Any] = {
            "task_id": task_id,
            "client_request_id": client_request_id,
            "message": message,
        }
        if request_digest is not None:
            payload["request_digest"] = request_digest
        if run_id is not None:
            payload["run_id"] = run_id
        return self._post("", json=payload)

    def queue(self) -> dict[str, Any]:
        """Return the bounded owner/global queue summary."""

        return self._get("queue/")

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return one owner-scoped durable run status snapshot."""

        return self._get(f"{run_id}/")

    def get_events(
        self,
        run_id: str,
        *,
        after: int | None = None,
    ) -> dict[str, Any]:
        """Replay bounded JSON events after an optional sequence cursor."""

        params: dict[str, Any] | None = None
        if after is not None:
            if isinstance(after, bool) or not isinstance(after, int) or after < 0:
                raise ValueError("after must be a non-negative integer")
            params = {"after": after}
        return self._get(f"{run_id}/events/", params=params)

    def iter_events(
        self,
        run_id: str,
        *,
        after: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield one bounded durable replay page from the server.

        The helper deliberately performs one owner-scoped request only.  A
        caller that reconnects supplies the last received sequence through
        ``after``; it never retries a mutation or hides a server-side error.
        The server remains responsible for execution and durable event order.
        """

        payload = self.get_events(run_id, after=after)
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            raise ValueError("events response must contain a list")
        for event in raw_events:
            if not isinstance(event, dict):
                raise ValueError("events response contains a non-object event")
            yield event

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Poll the server until one durable run reaches a terminal state.

        This is a client-side wait loop around the status endpoint.  It does
        not execute Agent work, enable queued runtime, or retry submission.
        A timeout is explicit so a disconnected caller cannot wait forever.
        """

        _require_positive_finite(timeout_seconds, "timeout_seconds")
        _require_positive_finite(poll_interval_seconds, "poll_interval_seconds")

        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.get_run(run_id)
            status = snapshot.get("status")
            if not isinstance(status, str) or not status:
                raise ValueError("run response must contain a non-empty status")
            if status in _TERMINAL_RUN_STATUSES:
                return snapshot

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SDKTimeoutError(f"Timed out waiting for run {run_id}")
            time.sleep(min(poll_interval_seconds, remaining))

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Request cooperative cancellation for one owner-scoped run."""

        return self._post(f"{run_id}/cancel/")

    # Short aliases keep the facade convenient without changing the wire
    # contract or duplicating any server-side behavior.
    create = create_run
    get = get_run
    events = get_events
    cancel = cancel_run


__all__ = ["TerminalAgentRunsModule"]


def _require_positive_finite(value: float, field_name: str) -> None:
    """Validate one finite positive polling duration."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a positive finite number")
    if not math.isfinite(float(value)) or value <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")
