"""Composition root for the ordinary stock-basic fenced capture use case."""

from __future__ import annotations

from apps.data_center.application.instrument_reference_capture_use_case import (
    CaptureInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.composition import get_provider_config_repository
from apps.data_center.infrastructure.instrument_reference_capture_completion_repository import (
    DjangoInstrumentReferenceCaptureCompletionRepository,
)
from apps.data_center.infrastructure.instrument_reference_capture_parser import (
    TushareStockBasicCaptureParser,
)
from apps.data_center.infrastructure.instrument_reference_capture_persistence import (
    DjangoInstrumentReferenceCapturePersistence,
)
from apps.data_center.infrastructure.instrument_reference_capture_provider import (
    CaptureResponseStageStore,
    TushareInstrumentReferenceCaptureProvider,
)
from apps.data_center.infrastructure.instrument_reference_snapshot_runtime import (
    create_instrument_reference_snapshot_repository,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
)


def create_instrument_reference_capture_use_case() -> CaptureInstrumentReferenceSnapshotUseCase:
    """Compose capture ports without registering a route or activating a provider."""

    snapshots = create_instrument_reference_snapshot_repository()
    claims = DjangoInstrumentReferenceCaptureCompletionRepository(snapshots)
    raw_payloads = RawLandingRepository()
    raw_audits = RawAuditRepository()
    response_stages = CaptureResponseStageStore()
    provider = TushareInstrumentReferenceCaptureProvider(
        get_provider_config_repository(),
        response_stages,
    )
    persistence = DjangoInstrumentReferenceCapturePersistence(
        claims,
        snapshots,
        raw_payloads,
        raw_audits,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(raw_audits),
        response_stages,
    )
    parser = TushareStockBasicCaptureParser()
    return CaptureInstrumentReferenceSnapshotUseCase(
        claims,
        provider,
        persistence,
        parser,
        parser,
    )


__all__ = ["create_instrument_reference_capture_use_case"]
