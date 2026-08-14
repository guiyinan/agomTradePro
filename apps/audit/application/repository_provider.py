"""Repository provider for audit application orchestration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.audit.infrastructure.providers import DjangoAuditRepository as DjangoAuditRepository

if TYPE_CHECKING:
    from apps.audit.application.system_audit_outbox_dispatcher import (
        DispatchSystemAuditOutboxUseCase,
    )
    from apps.audit.infrastructure.failure_counter import AuditFailureCounter
    from apps.audit.infrastructure.system_audit_outbox_repository import (
        DjangoSystemAuditOutboxRepository,
    )

logger = logging.getLogger(__name__)


def get_audit_repository() -> DjangoAuditRepository:
    """Return the configured audit repository implementation."""

    return DjangoAuditRepository()


def get_audit_outbox_repository(*, using: str = "default") -> DjangoSystemAuditOutboxRepository:
    """Return the read-only system-audit outbox repository implementation."""

    from apps.audit.infrastructure.system_audit_outbox_repository import (
        DjangoSystemAuditOutboxRepository,
    )

    return DjangoSystemAuditOutboxRepository(using=using)


def get_system_audit_outbox_dispatcher() -> DispatchSystemAuditOutboxUseCase:
    """Return a safe dispatcher or raise an application-level blocked reason."""

    from apps.audit.application.system_audit_outbox_dispatcher import (
        DispatchSystemAuditOutboxUseCase,
        SystemAuditOutboxDispatchUnavailable,
    )
    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        SystemAuditOutboxPublisherUnavailable,
    )
    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        get_system_audit_outbox_dispatcher as _impl,
    )

    try:
        dispatcher: DispatchSystemAuditOutboxUseCase = _impl()
    except SystemAuditOutboxPublisherUnavailable as exc:
        raise SystemAuditOutboxDispatchUnavailable(
            "system audit outbox publisher is not wired",
            reason_code=exc.reason_code,
        ) from None
    if not isinstance(dispatcher, DispatchSystemAuditOutboxUseCase):
        raise SystemAuditOutboxDispatchUnavailable(
            "system audit outbox dispatcher composition is invalid",
            reason_code="invalid_dispatch_composition",
        )
    return dispatcher


def project_audit_outbox_backlog_metrics() -> bool:
    """Project the default-alias outbox snapshot for the shared metrics scrape.

    The metrics endpoint is a read-only observation surface.  This facade
    fixes the database alias and observation clock so callers cannot project a
    fabricated tenant, timestamp, or high-cardinality label.  Any repository,
    codec, or metric projection failure is reduced to a stable warning and a
    ``False`` result; it must never prevent generic Prometheus metrics from
    being served.
    """

    from apps.audit.application.system_audit_outbox_observability import (
        GetSystemAuditOutboxBacklogCommand,
        GetSystemAuditOutboxBacklogUseCase,
    )
    from apps.audit.infrastructure.metrics import record_system_audit_outbox_backlog

    try:
        observed_at: datetime = timezone.now()
        reader = get_audit_outbox_repository(using="default")
        snapshot = GetSystemAuditOutboxBacklogUseCase(reader).execute(
            GetSystemAuditOutboxBacklogCommand(as_of=observed_at)
        )
        record_system_audit_outbox_backlog(snapshot)
        return True
    except Exception as exc:
        logger.warning(
            "Failed to project audit outbox metrics (error_type=%s)",
            type(exc).__name__,
        )
        return False


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
