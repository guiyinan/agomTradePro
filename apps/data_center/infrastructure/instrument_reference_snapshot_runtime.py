"""Composition root for default-alias instrument snapshot repositories."""

from __future__ import annotations

from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository

from .instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)


def create_instrument_reference_snapshot_repository() -> (
    DjangoInstrumentReferenceSnapshotRepository
):
    """Bind the existing exact RawAudit and RawPayload repositories on default."""

    return DjangoInstrumentReferenceSnapshotRepository(
        RawAuditRepository(),
        RawLandingRepository(),
    )


__all__ = ["create_instrument_reference_snapshot_repository"]
