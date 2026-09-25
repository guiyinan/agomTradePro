"""Shared audit-authority checks for DATA-02 Celery tasks."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.integration import data_center_audit as audit_integration
from shared.domain.task_outcomes import TaskBusinessOutcome

_FINALIZATION_WINDOW = timedelta(seconds=300)


def data02_authority_failure(reason: str) -> dict[str, object]:
    """Return a stable zero-write authority denial for DATA-02 tasks."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "stage": "authority",
        "blocked_reason": reason,
        "must_not_use_for_decision": True,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "checkpoint": {
            "offset": 0,
            "next_offset": 0,
            "total_assets": 0,
            "complete": False,
        },
    }


def preflight_data02_task_authority(
    *,
    as_of: datetime,
    minimum_window: timedelta,
    expected_actor: str = "",
) -> tuple[audit_integration.SystemAuditReaderContext | None, dict[str, object] | None]:
    """Resolve current authority and prove it covers the task's bounded runtime."""

    try:
        context = audit_integration.preflight_data_reliability_audit_runtime(
            environment="production",
            using="default",
            as_of=as_of,
        )
    except audit_integration.SystemAuditCompositionUnavailable as exc:
        return None, data02_authority_failure(f"system_audit_{exc.reason_code}")
    if expected_actor and expected_actor != context.actor_id:
        return None, data02_authority_failure("operator_actor_mismatch")
    if context.authority_valid_until < as_of + minimum_window:
        return None, data02_authority_failure("authority_window_too_short")
    return context, None


def same_data02_task_authority_is_current(
    authority: audit_integration.SystemAuditReaderContext,
    *,
    as_of: datetime,
    minimum_window: timedelta = _FINALIZATION_WINDOW,
) -> bool:
    """Allow an equivalent active successor while the starting grant remains valid."""

    current, failure = preflight_data02_task_authority(
        as_of=as_of,
        minimum_window=minimum_window,
        expected_actor=authority.actor_id,
    )
    if failure is not None or current is None:
        return False
    if authority.authority_valid_until < as_of + minimum_window:
        return False
    identity_fields = (
        "authority_source_id",
        "actor_id",
        "user_id",
        "tenant_id",
        "owner_id",
        "is_authenticated",
        "is_staff",
        "role",
    )
    return all(getattr(current, field) == getattr(authority, field) for field in identity_fields)
