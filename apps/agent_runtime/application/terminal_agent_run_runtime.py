"""Typed application contracts for the durable queued Terminal Agent runtime.

The module contains only transport-neutral DTOs and a Protocol.  Django ORM,
Celery, and the Agent SDK stay behind the infrastructure composition root.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from apps.agent_runtime.application.terminal_agent_run_api_contract import (
    JsonValue,
)
from apps.agent_runtime.application.terminal_agent_run_ports import (
    TerminalQueuedSubmissionRequest,
    TerminalRunQueueSummary,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentBrokerEnvelope,
    TerminalAgentRunContract,
    TerminalRunStatus,
)


@dataclass(frozen=True, slots=True)
class TerminalRunSnapshot:
    """Owner-scoped durable run status returned by API queries."""

    run_id: str
    task_id: int
    status: TerminalRunStatus
    accepted_at: datetime
    updated_at: datetime
    deadline_at: datetime
    claimed_by: str | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    error_code: str | None
    result_ref: str | None


@dataclass(frozen=True, slots=True)
class TerminalRunEventRecord:
    """One replayable, owner-scoped event for the SSE boundary."""

    event_id: str
    run_id: str
    event_type: str
    occurred_at: datetime
    sequence: int
    data: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class TerminalAgentWorkerInput:
    """Validated task payload reconstructed by the worker composition root."""

    run_id: str
    task_id: int
    actor_user_id: int
    message: str
    session_id: str
    username: str
    user_role: str
    user_is_admin: bool
    mcp_enabled: bool
    provider_ref: Any | None
    model: str | None
    context: Mapping[str, Any]


class TerminalQueuedRuntimePort(Protocol):
    """Infrastructure port for admission, execution state, and replay."""

    def submit(self, request: TerminalQueuedSubmissionRequest) -> TerminalAgentRunContract:
        """Persist one owner-scoped queued submission."""

        ...

    def claim(
        self,
        *,
        run_id: str,
        worker_id: str,
        claimed_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Atomically claim a queued run."""

        ...

    def get_for_owner(
        self,
        *,
        run_id: str,
        actor_user_id: int,
    ) -> TerminalAgentRunContract | None:
        """Return one owner-scoped contract."""

        ...

    def heartbeat(
        self,
        *,
        run_id: str,
        worker_id: str,
        heartbeat_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Refresh a worker lease."""

        ...

    def transition(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        target: TerminalRunStatus,
        worker_id: str | None = None,
        changed_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Apply one state transition."""

        ...

    def get_snapshot(self, *, run_id: str, actor_user_id: int) -> TerminalRunSnapshot | None:
        """Return a status snapshot only for the authenticated owner."""

        ...

    def cancel(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        requested_at: datetime,
    ) -> TerminalAgentRunContract | None:
        """Request cooperative cancellation in the same database transaction."""

        ...

    def list_events(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        after_sequence: int,
        limit: int,
    ) -> Sequence[TerminalRunEventRecord] | None:
        """Return replayable events after a validated sequence cursor."""

        ...

    def queue_summary(self, *, actor_user_id: int) -> TerminalRunQueueSummary:
        """Return bounded owner/global queue counters."""

        ...

    def list_queued_for_dispatch(
        self,
        *,
        before: datetime,
        limit: int,
    ) -> Sequence[TerminalAgentBrokerEnvelope]:
        """Return committed queued IDs eligible for broker reconciliation."""

        ...

    def append_event(
        self,
        *,
        run_id: str,
        worker_id: str,
        event_type: str,
        data: Mapping[str, JsonValue],
        occurred_at: datetime,
    ) -> TerminalRunEventRecord | None:
        """Append one worker event and return its replay identity."""

        ...

    def mark_finished(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: TerminalRunStatus,
        finished_at: datetime,
        error_code: str | None = None,
        result_ref: str | None = None,
        result_payload: Mapping[str, object] | None = None,
    ) -> TerminalAgentRunContract | None:
        """Persist a terminal execution outcome under the worker lease."""

        ...

    def mark_started(
        self,
        *,
        run_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> TerminalAgentRunContract | None:
        """Mark a claimed run as actively executing."""

        ...

    def get_worker_input(
        self,
        *,
        run_id: str,
        task_id: int,
    ) -> TerminalAgentWorkerInput | None:
        """Reconstruct an owner-bound Agent request from the task ledger."""

        ...

    def reap_stale(
        self,
        *,
        stale_before: datetime,
        reaped_at: datetime,
    ) -> int:
        """Move stale claimed/running leases to the durable orphan state."""

        ...
