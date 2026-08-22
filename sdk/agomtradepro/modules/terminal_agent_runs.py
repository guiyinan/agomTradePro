"""Client facade for the durable queued Terminal Agent run API."""

from __future__ import annotations

from typing import Any

from .base import BaseModule


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
            params = {"after": after}
        return self._get(f"{run_id}/events/", params=params)

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
