"""Governed, fail-closed Celery contract for audit outbox dispatch."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.audit.application.repository_provider import get_system_audit_outbox_dispatcher
from apps.audit.application.system_audit_outbox_dispatcher import (
    BlockedSystemAuditOutboxDispatchResult,
    DispatchSystemAuditOutboxCommand,
    SystemAuditOutboxDispatchUnavailable,
)

logger = logging.getLogger(__name__)


def _failure_result(*, reason_code: str, requested: int = 0) -> dict[str, object]:
    """Return bounded failure counters without exposing implementation details."""

    return {
        "outcome": "failed",
        "success": False,
        "reason_code": reason_code,
        "requested": requested,
        "claimed": 0,
        "delivered": 0,
        "failed": 1,
    }


def _parse_as_of(value: str | None) -> datetime:
    """Parse a timezone-aware task cutoff, defaulting to the server clock."""

    if value is None:
        return timezone.now()
    if not isinstance(value, str) or not value:
        raise ValueError("as_of_must_be_timezone_aware_iso")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("as_of_must_be_timezone_aware_iso") from exc
    if parsed.utcoffset() is None:
        raise ValueError("as_of_must_be_timezone_aware_iso")
    return parsed


def _build_command(
    *, limit: int, worker_id: str | None, as_of: str | None
) -> DispatchSystemAuditOutboxCommand:
    """Validate task-boundary values before any infrastructure composition."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit_must_be_between_1_and_100")
    if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 128:
        raise ValueError("worker_id_must_be_non_empty_and_bounded")
    return DispatchSystemAuditOutboxCommand(
        worker_id=worker_id,
        as_of=_parse_as_of(as_of),
        limit=limit,
    )


@shared_task(  # type: ignore[misc]
    bind=True,
    name="apps.audit.application.tasks.dispatch_system_audit_outbox_task",
    max_retries=0,
    time_limit=120,
    soft_time_limit=100,
)
def dispatch_system_audit_outbox_task(
    self: Any,
    limit: int = 20,
    worker_id: str | None = None,
    as_of: str | None = None,
) -> dict[str, object]:
    """Dispatch only through the configured durable and scoped audit runtime.

    Runtime configuration, authenticated authority, and the canonical sink are
    resolved before any repository claim.  An unavailable prerequisite remains
    a bounded blocked result and cannot become a false ``delivered`` transition.
    """

    del self
    try:
        command = _build_command(limit=limit, worker_id=worker_id, as_of=as_of)
    except (TypeError, ValueError) as exc:
        reason_code = str(exc) or "invalid_dispatch_input"
        requested = limit if isinstance(limit, int) and not isinstance(limit, bool) else 0
        return _failure_result(reason_code=reason_code, requested=requested)

    try:
        dispatcher = get_system_audit_outbox_dispatcher()
    except SystemAuditOutboxDispatchUnavailable as exc:
        return BlockedSystemAuditOutboxDispatchResult(
            requested=command.limit,
            reason_code=exc.reason_code,
        ).as_task_result()
    except Exception as exc:
        logger.warning(
            "Audit outbox dispatch composition failed (error_type=%s)",
            type(exc).__name__,
        )
        return _failure_result(
            reason_code="dispatch_composition_failed",
            requested=command.limit,
        )

    try:
        result = dispatcher.execute(command)
    except SystemAuditOutboxDispatchUnavailable as exc:
        logger.warning(
            "Audit outbox dispatch unavailable (error_type=%s)",
            type(exc).__name__,
        )
        if exc.reason_code in {"authority_not_wired", "authority_unavailable"}:
            return BlockedSystemAuditOutboxDispatchResult(
                requested=command.limit,
                reason_code=exc.reason_code,
            ).as_task_result()
        return _failure_result(reason_code=exc.reason_code, requested=command.limit)
    except Exception as exc:
        logger.warning(
            "Audit outbox dispatch failed (error_type=%s)",
            type(exc).__name__,
        )
        return _failure_result(
            reason_code="dispatch_execution_failed",
            requested=command.limit,
        )

    return {
        "outcome": result.outcome,
        "success": result.outcome in {"success", "noop"},
        "reason_code": "dispatch_completed" if result.delivered else "no_due_rows",
        "requested": result.requested,
        "claimed": result.claimed,
        "delivered": result.delivered,
        "failed": result.failed,
    }


__all__ = ["dispatch_system_audit_outbox_task"]
