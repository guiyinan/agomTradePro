"""Scheduled guard for the scoped System Audit authority lease.

The guard closes the operational gap between the append-only renewal command
and the Celery scheduler.  It never manufactures approval evidence: a
renewal is attempted only through the configured, hash-bound renewal request
executor.  Missing, stale, or rejected evidence remains a visible blocked
outcome and keeps the decision path fail-closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from shared.domain.task_outcomes import TaskBusinessOutcome

AUTHORITY_RENEWAL_GUARD_TASK_NAME = (
    "apps.audit.application.tasks.system_audit_authority_renewal_guard_task"
)
DEFAULT_RENEWAL_WINDOW = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityLease:
    """Read-only projection of the configured audit authority lease."""

    mode: str
    outbox_enabled: bool
    valid_until: datetime | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        """Reject an unbounded lease projection at the application boundary."""

        if self.mode not in {"off", "shadow", "required"}:
            raise ValueError("audit authority lease mode is invalid")
        if type(self.outbox_enabled) is not bool:
            raise TypeError("audit authority lease outbox flag must be boolean")
        if self.valid_until is not None and (
            type(self.valid_until) is not datetime
            or self.valid_until.tzinfo is None
            or self.valid_until.utcoffset() is None
        ):
            raise ValueError("audit authority lease validity must be timezone-aware")
        if self.reason_code is not None and (
            type(self.reason_code) is not str
            or not self.reason_code
            or len(self.reason_code) > 64
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in self.reason_code
            )
        ):
            raise ValueError("audit authority lease reason is invalid")


LeaseReader = Callable[[], SystemAuditAuthorityLease]
RenewalExecutor = Callable[[], dict[str, object]]
AlertPublisher = Callable[[str, str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityRenewalGuardDependencies:
    """Injected ports used by the scheduled renewal guard."""

    read_lease: LeaseReader
    execute_renewal: RenewalExecutor
    publish_alert: AlertPublisher
    clock: Callable[[], datetime] = timezone.now
    renewal_window: timedelta = DEFAULT_RENEWAL_WINDOW

    def __post_init__(self) -> None:
        """Validate clocks and the bounded renewal window once at composition."""

        if not callable(self.read_lease) or not callable(self.execute_renewal):
            raise TypeError("renewal guard readers and executor must be callable")
        if not callable(self.publish_alert) or not callable(self.clock):
            raise TypeError("renewal guard alert and clock ports must be callable")
        if type(self.renewal_window) is not timedelta or self.renewal_window <= timedelta(0):
            raise ValueError("renewal guard window must be positive")


def _counters(
    *, outcome: str, reason_code: str, seconds_remaining: float | None = None
) -> dict[str, object]:
    """Return the common Celery business-outcome counters."""

    result: dict[str, object] = {
        "outcome": outcome,
        "success": outcome in {TaskBusinessOutcome.SUCCESS.value, TaskBusinessOutcome.NOOP.value},
        "stage": (
            "complete"
            if outcome in {TaskBusinessOutcome.SUCCESS.value, TaskBusinessOutcome.NOOP.value}
            else "authority"
        ),
        "requested": 1,
        "succeeded": 1 if outcome == TaskBusinessOutcome.SUCCESS.value else 0,
        "failed": 1 if outcome == TaskBusinessOutcome.FAILED.value else 0,
        "stored": 0,
        "block_reason_code": reason_code,
    }
    if seconds_remaining is not None:
        result["seconds_remaining"] = max(0.0, seconds_remaining)
    return result


def _blocked(
    dependencies: SystemAuditAuthorityRenewalGuardDependencies,
    *,
    reason_code: str,
    message: str,
    metadata: dict[str, Any],
) -> dict[str, object]:
    """Publish one deduplicated operational alert and return a blocked result."""

    dependencies.publish_alert(
        "critical",
        "System Audit authority renewal blocked",
        {"reason_code": reason_code, **metadata, "message": message},
    )
    return _counters(outcome=TaskBusinessOutcome.BLOCKED.value, reason_code=reason_code)


def run_system_audit_authority_renewal_guard(
    dependencies: SystemAuditAuthorityRenewalGuardDependencies | None = None,
) -> dict[str, object]:
    """Renew a bounded authority before expiry or publish a stable blocker.

    The configured executor is the only component allowed to perform a write.
    A healthy lease is a ``noop``; a renewal result is passed through only
    after its outcome is checked.  Exceptions are converted into a redacted
    blocked result so the scheduler cannot report a false success.
    """

    active = dependencies or _default_dependencies()
    now = active.clock()
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("renewal guard clock must be timezone-aware")
    try:
        lease = active.read_lease()
    except Exception:
        return _blocked(
            active,
            reason_code="authority_lease_unavailable",
            message="无法读取审计授权租约，已阻止受保护数据写入。",
            metadata={},
        )
    if type(lease) is not SystemAuditAuthorityLease:
        return _blocked(
            active,
            reason_code="authority_lease_invalid",
            message="审计授权租约返回类型无效，已阻止受保护数据写入。",
            metadata={},
        )
    if lease.reason_code is not None:
        return _blocked(
            active,
            reason_code=lease.reason_code,
            message="审计授权租约不可用，未执行任何行情或审计写入。",
            metadata={"mode": lease.mode, "outbox_enabled": lease.outbox_enabled},
        )
    if lease.mode != "required" or not lease.outbox_enabled:
        return _blocked(
            active,
            reason_code="audit_runtime_disabled",
            message="审计运行时未处于 required/outbox 模式，未自动放行数据写入。",
            metadata={"mode": lease.mode, "outbox_enabled": lease.outbox_enabled},
        )
    if lease.valid_until is None:
        return _blocked(
            active,
            reason_code="authority_validity_missing",
            message="审计授权没有有效期，未自动放行数据写入。",
            metadata={},
        )
    remaining = (lease.valid_until - now).total_seconds()
    if remaining <= 0:
        return _blocked(
            active,
            reason_code="authority_expired_reapproval_required",
            message="底层审批凭据已过期，需要新的负责人审批证据后才能恢复。",
            metadata={"valid_until": lease.valid_until.isoformat()},
        )
    if lease.valid_until - now > active.renewal_window:
        return _counters(
            outcome=TaskBusinessOutcome.NOOP.value,
            reason_code="authority_window_healthy",
            seconds_remaining=remaining,
        )
    try:
        result = active.execute_renewal()
    except Exception:
        return _blocked(
            active,
            reason_code="authority_renewal_failed",
            message="自动续期执行失败，已保持阻断。",
            metadata={"seconds_remaining": max(0.0, remaining)},
        )
    if type(result) is not dict or result.get("outcome") not in {
        TaskBusinessOutcome.SUCCESS.value,
        TaskBusinessOutcome.NOOP.value,
        TaskBusinessOutcome.BLOCKED.value,
        TaskBusinessOutcome.FAILED.value,
    }:
        return _blocked(
            active,
            reason_code="authority_renewal_result_invalid",
            message="自动续期返回结果无效，已保持阻断。",
            metadata={"seconds_remaining": max(0.0, remaining)},
        )
    outcome = str(result["outcome"])
    if outcome in {TaskBusinessOutcome.SUCCESS.value, TaskBusinessOutcome.NOOP.value}:
        return {**result, "stage": "renewal", "seconds_remaining": max(0.0, remaining)}
    reason_code = result.get("block_reason_code") or result.get("reason_code")
    if type(reason_code) is not str or not reason_code:
        reason_code = "authority_renewal_rejected"
    return _blocked(
        active,
        reason_code=reason_code,
        message="自动续期未获得有效的底层审批证据，已保持阻断。",
        metadata={"seconds_remaining": max(0.0, remaining)},
    )


def _default_dependencies() -> SystemAuditAuthorityRenewalGuardDependencies:
    """Compose the scheduled guard at the infrastructure boundary."""

    from apps.audit.infrastructure.system_audit_authority_renewal_executor import (
        execute_configured_system_audit_authority_renewal,
    )
    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        get_system_audit_authority_lease,
    )
    from shared.infrastructure.operational_alert_registry import record_operational_alert

    def publish_alert(level: str, title: str, metadata: dict[str, Any]) -> None:
        """Persist one scheduler alert without exposing credentials."""

        message = str(metadata.get("message", title))
        alert_metadata = {key: value for key, value in metadata.items() if key != "message"}
        record_operational_alert(
            level=level,
            task_name=AUTHORITY_RENEWAL_GUARD_TASK_NAME,
            title=title,
            message=message,
            metadata=alert_metadata,
        )

    return SystemAuditAuthorityRenewalGuardDependencies(
        read_lease=get_system_audit_authority_lease,
        execute_renewal=execute_configured_system_audit_authority_renewal,
        publish_alert=publish_alert,
    )


__all__ = [
    "AUTHORITY_RENEWAL_GUARD_TASK_NAME",
    "DEFAULT_RENEWAL_WINDOW",
    "SystemAuditAuthorityLease",
    "SystemAuditAuthorityRenewalGuardDependencies",
    "run_system_audit_authority_renewal_guard",
]
