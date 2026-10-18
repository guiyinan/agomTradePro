"""Public exact-read composition for immutable instrument-reference receipts."""

from __future__ import annotations

from uuid import UUID

from apps.data_center.application.instrument_reference_snapshot import (
    GetInstrumentReferenceMappingUseCase,
    GetInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_runtime import (
    create_instrument_reference_snapshot_repository,
)


def read_instrument_reference_snapshot(
    *,
    snapshot_id: UUID,
) -> InstrumentReferenceSnapshotRecord | None:
    """Read and fully revalidate one exact persisted source snapshot."""

    repository = create_instrument_reference_snapshot_repository()
    return GetInstrumentReferenceSnapshotUseCase(repository).execute(snapshot_id)


def read_instrument_reference_mapping(
    *,
    mapping_record_id: UUID,
) -> InstrumentReferenceMappingRecord | None:
    """Read and fully revalidate one exact persisted mapping receipt."""

    repository = create_instrument_reference_snapshot_repository()
    return GetInstrumentReferenceMappingUseCase(repository).execute(mapping_record_id)


__all__ = [
    "read_instrument_reference_mapping",
    "read_instrument_reference_snapshot",
]
