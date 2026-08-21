"""Celery entry points for the dedicated Terminal Agent worker queue."""

from __future__ import annotations

import logging
import os
import socket
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
from apps.agent_runtime.domain.terminal_agent_run_contract import TerminalRunStatus

logger = logging.getLogger(__name__)
TERMINAL_AGENT_TASK_NAME = "apps.agent_runtime.application.tasks.execute_terminal_agent_run"
TERMINAL_AGENT_REAPER_TASK_NAME = (
    "apps.agent_runtime.application.tasks.reap_stale_terminal_agent_runs"
)
TERMINAL_AGENT_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    """Return the aware worker clock used for lifecycle writes."""

    return datetime.now(UTC)


def _repo() -> TerminalQueuedRuntimePort:
    """Build the infrastructure repository through the composition root."""

    return get_terminal_agent_run_repository()


def _result_payload(reply: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Build the bounded result envelope persisted for status/replay."""

    return {"reply": reply, "metadata": metadata}


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

    repository = _repo()
    claimed = repository.claim(
        run_id=run_id,
        worker_id=TERMINAL_AGENT_WORKER_ID,
        claimed_at=_now(),
    )
    if claimed is None:
        return {"outcome": "noop", "reason_code": "run_not_queued", "run_id": run_id}

    actor_user_id = claimed.submission.selector.actor_user_id
    started_at = _now()
    try:
        repository.mark_started(
            run_id=run_id,
            worker_id=TERMINAL_AGENT_WORKER_ID,
            started_at=started_at,
        )
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
            repository.heartbeat(
                run_id=run_id,
                worker_id=TERMINAL_AGENT_WORKER_ID,
                heartbeat_at=_now(),
            )
            repository.append_event(
                run_id=run_id,
                worker_id=TERMINAL_AGENT_WORKER_ID,
                event_type=event.event_type,
                data=event.data,
                occurred_at=_now(),
            )
            current = repository.get_for_owner(run_id=run_id, actor_user_id=actor_user_id)
            if (
                current is not None
                and current.dispatch_status is TerminalRunStatus.CANCEL_REQUESTED
            ):
                repository.transition(
                    run_id=run_id,
                    actor_user_id=actor_user_id,
                    target=TerminalRunStatus.CANCELLED,
                    worker_id=TERMINAL_AGENT_WORKER_ID,
                    changed_at=_now(),
                )
                return {"outcome": "partial", "reason_code": "cancelled", "run_id": run_id}
            if event.event_type == "message_delta":
                reply_parts.append(str(event.data.get("delta") or ""))
            elif event.event_type == "approval_required":
                repository.transition(
                    run_id=run_id,
                    actor_user_id=actor_user_id,
                    target=TerminalRunStatus.WAITING_APPROVAL,
                    worker_id=TERMINAL_AGENT_WORKER_ID,
                    changed_at=_now(),
                )
                return {"outcome": "success", "status": "waiting_approval", "run_id": run_id}
            elif event.event_type == "error":
                raise RuntimeError("terminal_agent_execution_failed")
            elif event.event_type == "final":
                final_metadata = dict(event.data.get("metadata") or {})
                final_reply = str(event.data.get("reply") or "")
                if final_reply:
                    reply_parts = [final_reply]
        reply = "".join(reply_parts)
        repository.mark_finished(
            run_id=run_id,
            worker_id=TERMINAL_AGENT_WORKER_ID,
            status=TerminalRunStatus.COMPLETED,
            finished_at=_now(),
            result_ref=f"run:{run_id}:result",
            result_payload=_result_payload(reply, final_metadata),
        )
        return {"outcome": "success", "status": "completed", "run_id": run_id}
    except Exception as exc:
        logger.warning(
            "Queued terminal run failed; run_id=%s exception_type=%s",
            run_id,
            type(exc).__name__,
        )
        repository.mark_finished(
            run_id=run_id,
            worker_id=TERMINAL_AGENT_WORKER_ID,
            status=TerminalRunStatus.FAILED,
            finished_at=_now(),
            error_code="terminal_agent_execution_failed",
        )
        return {
            "outcome": "failed",
            "reason_code": "terminal_agent_execution_failed",
            "run_id": run_id,
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
