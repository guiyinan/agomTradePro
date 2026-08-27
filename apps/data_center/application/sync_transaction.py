"""Typed transaction ports for audited Data Center synchronization."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from apps.audit.application.data_conflict_audit import DataConflictAuditObservation
from apps.audit.application.data_decision_read_audit import DataDecisionReadAuditObservation
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
from apps.audit.application.data_quality_audit import DataQualityAuditObservation
from apps.audit.application.data_repair_audit import DataRepairAuditObservation
from apps.audit.application.data_validation_audit import DataValidationRejectedObservation


class DataCenterSyncUnitOfWorkParticipant(Protocol):
    """One repository participating in a Django-backed sync transaction."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction identity, such as ``django:default``."""


class DataCenterSyncUnitOfWork(Protocol):
    """Outer transaction shared by facts, evidence, publication, and audit."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one non-nested transaction for a complete sync commit."""


class DataCenterSyncClock(Protocol):
    """Authoritative clock sampled by a sync use case."""

    def now(self) -> datetime:
        """Return one timezone-aware timestamp."""


class DataCenterSyncAuditWriter(Protocol):
    """One canonical audit writer participating in a sync transaction."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by the audit ledger and outbox."""


class DataFetchAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one persisted fetch observation."""

    def write(self, observation: DataFetchAuditObservation) -> object:
        """Append an exact fetch event/outbox pair or raise."""


class DataPublicationAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one publication observation."""

    def write(self, observation: DataPublicationAuditObservation) -> object:
        """Append an exact publication event/outbox pair or raise."""


class DataPublicationRollbackAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one explicit publication rollback."""

    def write(self, observation: DataPublicationRollbackAuditObservation) -> object:
        """Append an exact rollback event/outbox pair or raise."""


class DataValidationAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one validation rejection."""

    def write(self, observation: DataValidationRejectedObservation) -> object:
        """Append an exact validation event/outbox pair or raise."""


class DataFailoverAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one provider failover decision."""

    def write(self, observation: DataFailoverAuditObservation) -> object:
        """Append an exact failover event/outbox pair or raise."""


class DataDecisionReadAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one publication-bound decision read."""

    def write(self, observation: DataDecisionReadAuditObservation) -> object:
        """Append an exact decision-read event/outbox pair or raise."""


class DataFreshnessAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one publication freshness transition."""

    def write(self, observation: DataFreshnessAuditObservation) -> object | None:
        """Append a changed freshness event/outbox pair or return ``None``."""


class DataQualityAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one publication-quality transition."""

    def write(self, observation: DataQualityAuditObservation) -> object | None:
        """Append a changed quality event/outbox pair or return ``None``."""


class DataPublicationQualityRecorder(Protocol):
    """Reload and record quality for one exact canonical publication."""

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> DataQualityAuditObservation:
        """Verify and record one publication quality snapshot or raise."""


class DataConflictAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one reconciliation conflict transition."""

    def write(self, observation: DataConflictAuditObservation) -> object:
        """Append an exact conflict event/outbox pair or raise."""


class DataProviderHealthAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one provider circuit transition."""

    def write(self, observation: DataProviderHealthAuditObservation) -> object:
        """Append an exact provider-health event/outbox pair or raise."""


class DataRepairAuditWriter(DataCenterSyncAuditWriter, Protocol):
    """Canonical scoped writer for one completed reliability-repair run."""

    def write(self, observation: DataRepairAuditObservation) -> object:
        """Append an exact repair-completion event/outbox pair or raise."""


__all__ = [
    "DataCenterSyncClock",
    "DataCenterSyncAuditWriter",
    "DataCenterSyncUnitOfWork",
    "DataCenterSyncUnitOfWorkParticipant",
    "DataConflictAuditWriter",
    "DataFetchAuditWriter",
    "DataFailoverAuditWriter",
    "DataDecisionReadAuditWriter",
    "DataFreshnessAuditWriter",
    "DataQualityAuditWriter",
    "DataProviderHealthAuditWriter",
    "DataRepairAuditWriter",
    "DataPublicationAuditWriter",
    "DataPublicationQualityRecorder",
    "DataPublicationRollbackAuditWriter",
    "DataValidationAuditWriter",
]
