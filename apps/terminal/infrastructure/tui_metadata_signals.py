"""Cache invalidation hooks for published TUI metadata."""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save

from .models import TuiMetadataRegistryORM
from .tui_metadata_repository import PublishedTuiMetadataRepository


def _invalidate_runtime_metadata_cache(
    *,
    instance: TuiMetadataRegistryORM,
    **_kwargs: object,
) -> None:
    """Invalidate the active snapshot after registry mutations."""

    PublishedTuiMetadataRepository.invalidate_runtime_cache(instance.registry_key)


def register_tui_metadata_cache_signals() -> None:
    """Register idempotent metadata cache invalidation handlers."""

    dispatch_uid = "terminal.invalidate_tui_runtime_metadata"
    post_save.connect(
        _invalidate_runtime_metadata_cache,
        sender=TuiMetadataRegistryORM,
        dispatch_uid=f"{dispatch_uid}.save",
        weak=False,
    )
    post_delete.connect(
        _invalidate_runtime_metadata_cache,
        sender=TuiMetadataRegistryORM,
        dispatch_uid=f"{dispatch_uid}.delete",
        weak=False,
    )
