"""Small in-memory adapters for unit tests of audited Data Center sync paths."""

from __future__ import annotations

import dataclasses
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime

from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.audit.application.data_publication_audit import DataPublicationAuditObservation
from apps.audit.application.data_repair_audit import DataRepairAuditObservation
from apps.audit.application.data_validation_audit import DataValidationRejectedObservation
from apps.data_center.application.sync_identity import (
    SyncExecutionIdentity,
    build_sync_execution_identity,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash


class InMemorySyncUnitOfWork:
    """Expose the production UOW port without adding database behavior to unit tests."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the test transaction identity."""

        return "memory:test"

    def atomic(self) -> AbstractContextManager[None]:
        """Return a no-op context manager for isolated application tests."""

        return nullcontext()


class FixedSyncIdentityIssuer:
    """Issue a valid deterministic identity for the requested provider."""

    def issue(
        self,
        *,
        dataset_key: str,
        provider_name: str,
    ) -> SyncExecutionIdentity:
        """Return one canonical identity matching the request selectors."""

        return build_sync_execution_identity(
            run_id="11111111-1111-4111-8111-111111111111",
            ingested_run_id="22222222-2222-4222-8222-222222222222",
            batch_id="33333333-3333-4333-8333-333333333333",
            dataset_key=dataset_key,
            provider_name=provider_name,
        )


class CollectingDataFetchAuditWriter:
    """Collect exact fetch observations emitted by a unit under test."""

    def __init__(self) -> None:
        self.observations: list[DataFetchAuditObservation] = []

    @property
    def database_alias(self) -> str:
        """Return the test writer alias."""

        return "test"

    def write(self, observation: DataFetchAuditObservation) -> None:
        """Record one observation."""

        self.observations.append(observation)


class CollectingDataPublicationAuditWriter:
    """Collect exact publication observations emitted by a unit under test."""

    def __init__(self) -> None:
        self.observations: list[DataPublicationAuditObservation] = []

    @property
    def database_alias(self) -> str:
        """Return the test writer alias."""

        return "test"

    def write(self, observation: DataPublicationAuditObservation) -> None:
        """Record one observation."""

        self.observations.append(observation)


class CollectingDataValidationAuditWriter:
    """Collect exact validation-rejection observations emitted by a unit under test."""

    def __init__(self) -> None:
        self.observations: list[DataValidationRejectedObservation] = []

    @property
    def database_alias(self) -> str:
        """Return the test writer alias."""

        return "test"

    def write(self, observation: DataValidationRejectedObservation) -> None:
        """Record one validation-rejection observation."""

        self.observations.append(observation)


class CollectingDataRepairAuditWriter:
    """Collect exact repair-parent observations emitted by a unit under test."""

    def __init__(self) -> None:
        self.observations: list[DataRepairAuditObservation] = []

    @property
    def database_alias(self) -> str:
        """Return the test writer alias."""

        return "test"

    def write(self, observation: DataRepairAuditObservation) -> None:
        """Record one repair completion observation."""

        self.observations.append(observation)


class FixedSyncClock:
    """Return one stable timezone-aware test timestamp."""

    def __init__(self, value: datetime | None = None) -> None:
        self._value = value or datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        """Return the configured timestamp."""

        return self._value


def bind_raw_audit(audit: RawAudit, *, raw_audit_id: str = "raw-test-1") -> RawAudit:
    """Return one repository-shaped RawAudit with its exact id and content hash."""

    return dataclasses.replace(
        audit,
        raw_audit_id=raw_audit_id,
        content_hash=raw_audit_content_hash(audit),
    )


__all__ = [
    "CollectingDataFetchAuditWriter",
    "CollectingDataPublicationAuditWriter",
    "CollectingDataRepairAuditWriter",
    "CollectingDataValidationAuditWriter",
    "FixedSyncClock",
    "FixedSyncIdentityIssuer",
    "InMemorySyncUnitOfWork",
    "bind_raw_audit",
]
