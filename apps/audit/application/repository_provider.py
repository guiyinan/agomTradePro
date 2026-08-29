"""Repository provider for audit application orchestration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.audit.infrastructure.providers import DjangoAuditRepository as DjangoAuditRepository

if TYPE_CHECKING:
    from apps.audit.application.data_conflict_audit import (
        AppendDataConflictAuditObservationUseCase,
    )
    from apps.audit.application.data_decision_read_audit import (
        AppendDataDecisionReadAuditObservationUseCase,
    )
    from apps.audit.application.data_failover_audit import (
        AppendDataFailoverAuditObservationUseCase,
    )
    from apps.audit.application.data_fetch_audit import (
        AppendDataFetchAuditObservationUseCase,
    )
    from apps.audit.application.data_freshness_audit import (
        AppendDataFreshnessAuditObservationUseCase,
    )
    from apps.audit.application.data_provider_health_audit import (
        AppendDataProviderHealthAuditObservationUseCase,
    )
    from apps.audit.application.data_publication_audit import (
        AppendDataPublicationAuditObservationUseCase,
    )
    from apps.audit.application.data_publication_rollback_audit import (
        AppendDataPublicationRollbackAuditObservationUseCase,
    )
    from apps.audit.application.data_quality_audit import (
        AppendDataQualityAuditObservationUseCase,
    )
    from apps.audit.application.data_repair_audit import (
        AppendDataRepairAuditObservationUseCase,
    )
    from apps.audit.application.data_validation_audit import (
        AppendDataValidationRejectedObservationUseCase,
    )
    from apps.audit.application.system_audit_outbox_dispatcher import (
        DispatchSystemAuditOutboxUseCase,
    )
    from apps.audit.application.system_audit_query import SystemAuditQueryRepository
    from apps.audit.infrastructure.failure_counter import AuditFailureCounter
    from apps.audit.infrastructure.system_audit_outbox_repository import (
        DjangoSystemAuditOutboxRepository,
    )

logger = logging.getLogger(__name__)


def get_audit_repository() -> DjangoAuditRepository:
    """Return the configured audit repository implementation."""

    return DjangoAuditRepository()


def get_system_audit_event_repository(*, using: str = "default") -> SystemAuditQueryRepository:
    """Return the system-audit query repository for one database alias."""

    from apps.audit.infrastructure.system_audit_repository import (
        DjangoSystemAuditEventRepository,
    )

    return DjangoSystemAuditEventRepository(using=using)


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
            "system audit outbox runtime is unavailable",
            reason_code=exc.reason_code,
        ) from None
    if not isinstance(dispatcher, DispatchSystemAuditOutboxUseCase):
        raise SystemAuditOutboxDispatchUnavailable(
            "system audit outbox dispatcher composition is invalid",
            reason_code="invalid_dispatch_composition",
        )
    return dispatcher


def get_data_fetch_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataFetchAuditObservationUseCase:
    """Return the canonical scoped Data Center fetch-event writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_fetch_audit_writer,
    )

    return build_data_fetch_audit_writer(environment=environment, using=using)


def get_data_decision_read_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataDecisionReadAuditObservationUseCase:
    """Return the canonical scoped decision-read event writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_decision_read_audit_writer,
    )

    return build_data_decision_read_audit_writer(environment=environment, using=using)


def get_data_provider_health_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataProviderHealthAuditObservationUseCase:
    """Return the canonical scoped provider circuit-transition writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_provider_health_audit_writer,
    )

    return build_data_provider_health_audit_writer(environment=environment, using=using)


def get_data_freshness_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataFreshnessAuditObservationUseCase:
    """Return the canonical scoped publication-freshness transition writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_freshness_audit_writer,
    )

    return build_data_freshness_audit_writer(environment=environment, using=using)


def get_data_quality_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataQualityAuditObservationUseCase:
    """Return the canonical scoped publication-quality transition writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_quality_audit_writer,
    )

    return build_data_quality_audit_writer(environment=environment, using=using)


def get_data_repair_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataRepairAuditObservationUseCase:
    """Return the canonical scoped reliability-repair completion writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_repair_audit_writer,
    )

    return build_data_repair_audit_writer(environment=environment, using=using)


def get_data_conflict_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataConflictAuditObservationUseCase:
    """Return the canonical scoped reconciliation-conflict writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_conflict_audit_writer,
    )

    return build_data_conflict_audit_writer(environment=environment, using=using)


def get_data_publication_rollback_audit_writer(
    *, environment: str = "production", using: str = "default"
) -> AppendDataPublicationRollbackAuditObservationUseCase:
    """Return the canonical scoped publication-rollback writer."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_publication_rollback_audit_writer,
    )

    return build_data_publication_rollback_audit_writer(
        environment=environment,
        using=using,
    )


def get_data_reliability_audit_writers(
    *, environment: str = "production", using: str = "default"
) -> tuple[
    AppendDataFetchAuditObservationUseCase,
    AppendDataPublicationAuditObservationUseCase,
    AppendDataValidationRejectedObservationUseCase,
    AppendDataFailoverAuditObservationUseCase,
    AppendDataDecisionReadAuditObservationUseCase,
    AppendDataProviderHealthAuditObservationUseCase,
    AppendDataFreshnessAuditObservationUseCase,
    AppendDataQualityAuditObservationUseCase,
]:
    """Return Data Reliability writers bound to one authority composition."""

    from apps.audit.infrastructure.system_audit_outbox_runtime import (
        build_data_reliability_audit_writers,
    )

    return build_data_reliability_audit_writers(
        environment=environment,
        using=using,
    )


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
