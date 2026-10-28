"""Compose explicit source-fact capture, recording and offline unpublished reads."""

from __future__ import annotations

from apps.data_center.application.price_limit_snapshot import (
    CapturePriceLimitSnapshotUseCase,
    ReadPriceLimitSnapshotUseCase,
    RecordPriceLimitSnapshotUseCase,
)
from apps.data_center.infrastructure.price_limit_snapshot_repository import (
    DjangoPriceLimitSnapshotRepository,
)
from apps.data_center.price_limit_capture_composition import build_price_limit_capture_use_case


def build_price_limit_snapshot_recorder() -> RecordPriceLimitSnapshotUseCase:
    """Record already retained responses through the sole canonical fact repository."""
    return RecordPriceLimitSnapshotUseCase(DjangoPriceLimitSnapshotRepository())


def build_price_limit_snapshot_capture() -> CapturePriceLimitSnapshotUseCase:
    """Reuse explicit configured capture without adding scheduling or publication."""
    return CapturePriceLimitSnapshotUseCase(
        build_price_limit_capture_use_case(), build_price_limit_snapshot_recorder()
    )


def build_price_limit_snapshot_reader() -> ReadPriceLimitSnapshotUseCase:
    """Read and revalidate facts without provider configuration or network access."""
    return ReadPriceLimitSnapshotUseCase(DjangoPriceLimitSnapshotRepository())
