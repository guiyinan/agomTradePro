"""Celery entry points for the dedicated Terminal Agent worker queue."""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task
from django.conf import settings

from apps.agent_runtime.application.repository_provider import get_terminal_agent_service
from apps.agent_runtime.application.terminal_agent import TerminalAgentChatRequestDTO
from apps.agent_runtime.application.terminal_agent_run_runtime import (
    TerminalQueuedRuntimePort,
)
from apps.agent_runtime.composition import get_terminal_agent_run_repository
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentBrokerEnvelope,
    TerminalRunStatus,
)

logger = logging.getLogger(__name__)
TERMINAL_AGENT_TASK_NAME = "apps.agent_runtime.application.tasks.execute_terminal_agent_run"
TERMINAL_AGENT_REAPER_TASK_NAME = (
    "apps.agent_runtime.application.tasks.reap_stale_terminal_agent_runs"
)
TERMINAL_AGENT_RECONCILIATION_TASK_NAME = (
    "apps.agent_runtime.application.tasks.reconcile_queued_terminal_agent_dispatch"
)


class _TerminalWorkerLeaseLost(RuntimeError):
    """Internal signal that this delivery no longer owns the durable lease."""


def _new_worker_id() -> str:
    """Return one delivery-scoped worker identity.

    A module-level ``hostname:pid`` value is shared by every prefork delivery
    in the process and cannot distinguish an old redelivery from its winner.
    The random suffix is intentionally generated after each task invocation so
    every claim and subsequent lifecycle write carries one unique capability.
    """

    hostname = socket.gethostname()[:48]
    return f"{hostname}:{os.getpid()}:{uuid.uuid4().hex}"


def _now() -> datetime:
    """Return the aware worker clock used for lifecycle writes."""

    return datetime.now(UTC)


def _repo() -> TerminalQueuedRuntimePort:
    """Build the infrastructure repository through the composition root."""

    return get_terminal_agent_run_repository()


def _result_payload(reply: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Build the bounded result envelope persisted for status/replay."""

    return {"reply": reply, "metadata": metadata}


def _queued_dispatch_block_reason() -> str | None:
    """Return the stable reason when queued dispatch must remain dormant."""

    if bool(getattr(settings, "TERMINAL_EMERGENCY_STOP", False)):
        return "submissions_paused"
    if not bool(getattr(settings, "TERMINAL_QUEUED_INTAKE_ENABLED", False)):
        return "queued_intake_disabled"
    if not bool(getattr(settings, "TERMINAL_QUEUED_WORKER_ENABLED", False)):
        return "queued_worker_disabled"
    return None


def _dispatch_broker_envelope(envelope: TerminalAgentBrokerEnvelope) -> None:
    """Publish one ID-only envelope to the dedicated terminal queue."""

    execute_terminal_agent_run.apply_async(
        args=[envelope.run_id, envelope.task_id],
        queue="terminal_agent",
    )


@shared_task(  # type: ignore[misc]
    name=TERMINAL_AGENT_TASK_NAME,
    bind=False,
    queue="terminal_agent",
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=120,
    soft_time_limit=110,
)
def execute_terminal_agent_run(run_id: str, task_id: int) -> dict[str, object]:
    """Claim, execute, checkpoint, and finish one ID-only broker envelope."""

    if not bool(getattr(settings, "TERMINAL_QUEUED_WORKER_ENABLED", False)):
        return {"outcome": "blocked", "reason_code": "queued_worker_disabled"}
    if bool(getattr(settings, "TERMINAL_EMERGENCY_STOP", False)):
        return {"outcome": "blocked", "reason_code": "submissions_paused"}

    repository = _repo()
    worker_id = _new_worker_id()
    claimed = repository.claim(
        run_id=run_id,
        worker_id=worker_id,
        claimed_at=_now(),
    )
    if claimed is None:
        return {"outcome": "noop", "reason_code": "run_not_queued", "run_id": run_id}

    actor_user_id = claimed.submission.selector.actor_user_id
    started_at = _now()
    try:
        if (
            repository.mark_started(
                run_id=run_id,
                worker_id=worker_id,
                started_at=started_at,
            )
            is None
        ):
            raise _TerminalWorkerLeaseLost()
        worker_input = repository.get_worker_input(run_id=run_id, task_id=task_id)
        if worker_input is None or worker_input.actor_user_id != actor_user_id:
            raise RuntimeError("terminal_worker_input_unavailable")
        service = get_terminal_agent_service()
        request = TerminalAgentChatRequestDTO(
            message=worker_input.message,
            session_id=worker_input.session_id,
            user_id=worker_input.actor_user_id,
            username=worker_input.username,
            user_role=worker_input.user_role,
            user_is_admin=worker_input.user_is_admin,
            mcp_enabled=worker_input.mcp_enabled,
            provider_ref=worker_input.provider_ref,
            model=worker_input.model,
            context=dict(worker_input.context),
        )
        reply_parts: list[str] = []
        final_metadata: dict[str, Any] = {}
        for event in service.stream_chat(request):
            if (
                repository.heartbeat(
                    run_id=run_id,
                    worker_id=worker_id,
                    heartbeat_at=_now(),
                )
                is None
            ):
                raise _TerminalWorkerLeaseLost()
            if (
                repository.append_event(
                    run_id=run_id,
                    worker_id=worker_id,
                    event_type=event.event_type,
                    data=event.data,
                    occurred_at=_now(),
                )
                is None
            ):
                raise _TerminalWorkerLeaseLost()
            current = repository.get_for_owner(run_id=run_id, actor_user_id=actor_user_id)
            if current is None:
                raise _TerminalWorkerLeaseLost()
            if current.dispatch_status is TerminalRunStatus.CANCEL_REQUESTED:
                if (
                    repository.transition(
                        run_id=run_id,
                        actor_user_id=actor_user_id,
                        target=TerminalRunStatus.CANCELLED,
                        worker_id=worker_id,
                        changed_at=_now(),
                    )
                    is None
                ):
                    raise _TerminalWorkerLeaseLost()
                return {"outcome": "partial", "reason_code": "cancelled", "run_id": run_id}
            if event.event_type == "message_delta":
                reply_parts.append(str(event.data.get("delta") or ""))
            elif event.event_type == "approval_required":
                if (
                    repository.transition(
                        run_id=run_id,
                        actor_user_id=actor_user_id,
                        target=TerminalRunStatus.WAITING_APPROVAL,
                        worker_id=worker_id,
                        changed_at=_now(),
                    )
                    is None
                ):
                    raise _TerminalWorkerLeaseLost()
                return {"outcome": "success", "status": "waiting_approval", "run_id": run_id}
            elif event.event_type == "error":
                raise RuntimeError("terminal_agent_execution_failed")
            elif event.event_type == "final":
                final_metadata = dict(event.data.get("metadata") or {})
                final_reply = str(event.data.get("reply") or "")
                if final_reply:
                    reply_parts = [final_reply]
        reply = "".join(reply_parts)
        if (
            repository.mark_finished(
                run_id=run_id,
                worker_id=worker_id,
                status=TerminalRunStatus.COMPLETED,
                finished_at=_now(),
                result_ref=f"run:{run_id}:result",
                result_payload=_result_payload(reply, final_metadata),
            )
            is None
        ):
            raise _TerminalWorkerLeaseLost()
        return {"outcome": "success", "status": "completed", "run_id": run_id}
    except _TerminalWorkerLeaseLost:
        logger.warning("Queued terminal run lease lost; run_id=%s", run_id)
        return {
            "outcome": "blocked",
            "reason_code": "worker_lease_lost",
            "run_id": run_id,
        }
    except Exception as exc:
        logger.warning(
            "Queued terminal run failed; run_id=%s exception_type=%s",
            run_id,
            type(exc).__name__,
        )
        try:
            failed = repository.mark_finished(
                run_id=run_id,
                worker_id=worker_id,
                status=TerminalRunStatus.FAILED,
                finished_at=_now(),
                error_code="terminal_agent_execution_failed",
            )
        except Exception:
            logger.warning("Queued terminal run failure checkpoint lost; run_id=%s", run_id)
            failed = None
        if failed is None:
            return {
                "outcome": "blocked",
                "reason_code": "worker_lease_lost",
                "run_id": run_id,
            }
        return {
            "outcome": "failed",
            "reason_code": "terminal_agent_execution_failed",
            "run_id": run_id,
        }


@shared_task(  # type: ignore[misc]
    name=TERMINAL_AGENT_RECONCILIATION_TASK_NAME,
    bind=False,
    queue="celery",
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=30,
    soft_time_limit=20,
)
def reconcile_queued_terminal_agent_dispatch(
    limit: int = 100,
) -> dict[str, object]:
    """Re-publish committed queued IDs after a transient broker failure.

    The task is deliberately fail-closed while either queued feature flag is
    disabled or the emergency stop is active.  It never claims, mutates, or
    executes a run; the dedicated worker's row-locked claim handles duplicate
    deliveries safely.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        return {
            "outcome": "failed",
            "success": False,
            "reason_code": "DISPATCH_RECONCILIATION_LIMIT_INVALID",
            "requested": 0,
            "examined": 0,
            "dispatched": 0,
            "failed": 0,
        }
    blocked_reason = _queued_dispatch_block_reason()
    if blocked_reason is not None:
        return {
            "outcome": "blocked",
            "success": False,
            "reason_code": blocked_reason,
            "requested": limit,
            "examined": 0,
            "dispatched": 0,
            "failed": 0,
        }

    grace_seconds = max(
        0,
        int(getattr(settings, "TERMINAL_AGENT_DISPATCH_RETRY_AFTER_SECONDS", 15)),
    )
    before = _now() - timedelta(seconds=grace_seconds)
    try:
        candidates = _repo().list_queued_for_dispatch(before=before, limit=limit)
    except Exception as exc:
        logger.warning(
            "Queued terminal dispatch reconciliation lookup failed; error_type=%s",
            type(exc).__name__,
        )
        return {
            "outcome": "failed",
            "success": False,
            "reason_code": "dispatch_reconciliation_lookup_failed",
            "requested": limit,
            "examined": 0,
            "dispatched": 0,
            "failed": 0,
        }

    dispatched = 0
    failed = 0
    for envelope in candidates:
        try:
            _dispatch_broker_envelope(envelope)
        except Exception as exc:
            failed += 1
            logger.warning(
                "Queued terminal dispatch reconciliation publish failed; " "error_type=%s",
                type(exc).__name__,
            )
        else:
            dispatched += 1

    if failed and dispatched:
        outcome = "partial"
        reason_code = "dispatch_reconciliation_partial"
    elif failed:
        outcome = "failed"
        reason_code = "dispatch_reconciliation_failed"
    elif dispatched:
        outcome = "success"
        reason_code = "dispatch_reconciliation_completed"
    else:
        outcome = "noop"
        reason_code = "no_queued_runs"
    return {
        "outcome": outcome,
        "success": outcome in {"success", "noop"},
        "reason_code": reason_code,
        "requested": limit,
        "examined": len(candidates),
        "dispatched": dispatched,
        "failed": failed,
    }


@shared_task(  # type: ignore[misc]
    name=TERMINAL_AGENT_REAPER_TASK_NAME,
    bind=False,
    queue="celery",
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=30,
    soft_time_limit=20,
)
def reap_stale_terminal_agent_runs() -> dict[str, object]:
    """Convert stale worker leases into explicit orphan evidence."""

    if not bool(getattr(settings, "TERMINAL_QUEUED_WORKER_ENABLED", False)):
        return {"outcome": "blocked", "reason_code": "queued_worker_disabled"}
    now = _now()
    grace_seconds = max(
        30,
        int(getattr(settings, "TERMINAL_AGENT_ORPHAN_AFTER_SECONDS", 90)),
    )
    reaped = _repo().reap_stale(
        stale_before=now - timedelta(seconds=grace_seconds),
        reaped_at=now,
    )
    return {"outcome": "success", "reaped": reaped}
