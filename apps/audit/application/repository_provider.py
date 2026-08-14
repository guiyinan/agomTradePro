"""Repository provider for audit application orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.audit.infrastructure.providers import DjangoAuditRepository as DjangoAuditRepository

if TYPE_CHECKING:
    from apps.audit.infrastructure.failure_counter import AuditFailureCounter
    from apps.audit.infrastructure.system_audit_outbox_repository import (
        DjangoSystemAuditOutboxRepository,
    )


def get_audit_repository() -> DjangoAuditRepository:
    """Return the configured audit repository implementation."""

    return DjangoAuditRepository()


def get_audit_outbox_repository() -> DjangoSystemAuditOutboxRepository:
    """Return the read-only system-audit outbox repository implementation."""

    from apps.audit.infrastructure.system_audit_outbox_repository import (
        DjangoSystemAuditOutboxRepository,
    )

    return DjangoSystemAuditOutboxRepository()


def record_audit_write_success(**kwargs: Any) -> None:
    """Record a successful audit write lazily."""

    from apps.audit.infrastructure.metrics import record_audit_write_success as _impl

    _impl(**kwargs)


def record_audit_write_failure(**kwargs: Any) -> None:
    """Record a failed audit write lazily."""

    from apps.audit.infrastructure.metrics import record_audit_write_failure as _impl

    _impl(**kwargs)


def record_audit_failure(**kwargs: Any) -> None:
    """Record a failure counter event lazily."""

    from apps.audit.infrastructure.failure_counter import record_audit_failure as _impl

    _impl(**kwargs)


def get_audit_failure_counter() -> AuditFailureCounter:
    """Return the shared audit failure counter."""

    from apps.audit.infrastructure.failure_counter import get_audit_failure_counter as _impl

    return _impl()


def get_audit_metrics_summary() -> dict[str, object]:
    """Return the current audit metrics summary."""

    from apps.audit.infrastructure.metrics import get_audit_metrics_summary as _impl

    return dict(_impl())


def export_audit_metrics() -> str:
    """Export Prometheus-formatted audit metrics."""

    from apps.audit.infrastructure.metrics import export_metrics as _impl

    return _impl()
