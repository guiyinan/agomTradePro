"""Composition-root facade for Data Center's canonical Audit integration.

Data Center is a platform dependency for Audit, so it must not import the
Audit app directly.  This module is the explicit cross-app composition root:
it exposes the stable Audit contracts and concrete factories needed while
keeping the Data Center app dependency graph one-way.
"""

from typing import Any

from apps.audit.application.data_conflict_audit import (
    DataConflictAuditObservation,
    DataConflictTransition,
)
from apps.audit.application.data_decision_read_audit import (
    DataDecisionReadAuditObservation,
)
from apps.audit.application.data_failover_audit import DataFailoverAuditObservation
from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.audit.application.data_freshness_audit import DataFreshnessAuditObservation
from apps.audit.application.data_provider_health_audit import (
    DataProviderHealthAuditObservation,
)
from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.application.data_publication_rollback_audit import (
    DataPublicationRollbackAuditObservation,
)
from apps.audit.application.data_quality_audit import (
    DataQualityAuditObservation,
    DataQualityState,
    DataQualityStatusCount,
)
from apps.audit.application.data_repair_audit import (
    DataRepairAuditObservation,
    RepairPublicationEvidence,
    RepairSectionEvidence,
)
from apps.audit.application.data_validation_audit import (
    DataValidationRejectedObservation,
)
from apps.audit.application.system_audit_query import (
    ListCorrelatedSystemAuditEventsCommand,
    ListCorrelatedSystemAuditEventsResult,
    ListCorrelatedSystemAuditEventsUseCase,
    SystemAuditQueryCorruption,
    SystemAuditQueryRepository,
    SystemAuditQueryUnavailable,
    SystemAuditReaderContext,
)
from apps.audit.domain.system_audit_event import (
    AuditCategory,
    AuditEvidenceRef,
    AuditOutcome,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)


def get_data_conflict_audit_writer(*, environment: str, using: str) -> Any:
    """Build the Audit-owned conflict writer after Django app initialization."""

    from apps.audit.application.repository_provider import (
        get_data_conflict_audit_writer as build_writer,
    )

    return build_writer(environment=environment, using=using)


def get_data_publication_rollback_audit_writer(*, environment: str, using: str) -> Any:
    """Build the Audit-owned rollback writer after Django app initialization."""

    from apps.audit.application.repository_provider import (
        get_data_publication_rollback_audit_writer as build_writer,
    )

    return build_writer(environment=environment, using=using)


def get_data_reliability_audit_writers(*, environment: str, using: str) -> Any:
    """Build the canonical Audit writer bundle at the composition boundary."""

    from apps.audit.application.repository_provider import (
        get_data_reliability_audit_writers as build_writers,
    )

    return build_writers(environment=environment, using=using)


def get_data_repair_audit_writer(*, environment: str, using: str) -> Any:
    """Build the Audit-owned repair writer after Django app initialization."""

    from apps.audit.application.repository_provider import (
        get_data_repair_audit_writer as build_writer,
    )

    return build_writer(environment=environment, using=using)


def get_system_audit_event_repository() -> SystemAuditQueryRepository:
    """Build the concrete Audit event repository at the composition boundary."""

    from apps.audit.application.repository_provider import (
        get_system_audit_event_repository as build_repository,
    )

    return build_repository()


__all__ = [
    "AuditCategory",
    "AuditEvidenceRef",
    "AuditOutcome",
    "AuditSeverity",
    "AuditWritePolicy",
    "DataConflictAuditObservation",
    "DataConflictTransition",
    "DataDecisionReadAuditObservation",
    "DataFailoverAuditObservation",
    "DataFetchAuditObservation",
    "DataFreshnessAuditObservation",
    "DataProviderHealthAuditObservation",
    "DataPublicationAuditObservation",
    "DataPublicationRollbackAuditObservation",
    "DataQualityAuditObservation",
    "DataQualityState",
    "DataQualityStatusCount",
    "DataRepairAuditObservation",
    "DataValidationRejectedObservation",
    "ListCorrelatedSystemAuditEventsCommand",
    "ListCorrelatedSystemAuditEventsResult",
    "ListCorrelatedSystemAuditEventsUseCase",
    "RepairPublicationEvidence",
    "RepairSectionEvidence",
    "SystemAuditEvent",
    "SystemAuditQueryCorruption",
    "SystemAuditQueryRepository",
    "SystemAuditQueryUnavailable",
    "SystemAuditReaderContext",
    "get_data_conflict_audit_writer",
    "get_data_publication_rollback_audit_writer",
    "get_data_reliability_audit_writers",
    "get_data_repair_audit_writer",
    "get_system_audit_event_repository",
]
