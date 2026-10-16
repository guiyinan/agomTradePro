"""Application ports and use cases for immutable instrument snapshots."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)


class InstrumentReferenceSnapshotRepositoryPort(Protocol):
    """Persist and read exact instrument mapping and snapshot receipts."""

    def save_mapping(
        self,
        content: InstrumentReferenceMappingContent,
    ) -> InstrumentReferenceMappingRecord:
        """Append mapping content using repository-owned first-record time."""

    def save_snapshot(
        self,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Append one complete RawAudit-bound snapshot without partial rows."""

    def get_snapshot(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Return one fully revalidated snapshot by exact immutable identity."""


class SaveInstrumentReferenceMappingUseCase:
    """Application entry for appending an explicit versioned mapping."""

    def __init__(self, repository: InstrumentReferenceSnapshotRepositoryPort) -> None:
        """Inject the repository boundary without exposing persistence details."""

        self._repository = repository

    def execute(
        self,
        content: InstrumentReferenceMappingContent,
    ) -> InstrumentReferenceMappingRecord:
        """Persist or return the exact immutable mapping receipt."""

        return self._repository.save_mapping(content)


class SaveInstrumentReferenceSnapshotUseCase:
    """Application entry for persisting a complete source candidate snapshot."""

    def __init__(self, repository: InstrumentReferenceSnapshotRepositoryPort) -> None:
        """Inject the exact-evidence repository boundary."""

        self._repository = repository

    def execute(
        self,
        content: InstrumentReferenceSnapshotContent,
    ) -> InstrumentReferenceSnapshotRecord:
        """Persist one complete snapshot or return its exact prior receipt."""

        return self._repository.save_snapshot(content)


class GetInstrumentReferenceSnapshotUseCase:
    """Application query for an exact snapshot with evidence verification."""

    def __init__(self, repository: InstrumentReferenceSnapshotRepositoryPort) -> None:
        """Inject the repository responsible for full source/audit readback."""

        self._repository = repository

    def execute(self, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        """Read one exact snapshot and fail closed when any bound row is absent."""

        return self._repository.get_snapshot(snapshot_id)


__all__ = [
    "GetInstrumentReferenceSnapshotUseCase",
    "InstrumentReferenceSnapshotRepositoryPort",
    "SaveInstrumentReferenceMappingUseCase",
    "SaveInstrumentReferenceSnapshotUseCase",
]
