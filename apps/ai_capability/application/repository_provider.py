"""Repository provider helpers for AI capability application consumers."""

from __future__ import annotations

from apps.ai_capability.infrastructure.repositories import (
    DjangoCapabilityRepository,
    DjangoSyncLogRepository,
)


def get_capability_repository() -> DjangoCapabilityRepository:
    """Return the capability repository."""

    return DjangoCapabilityRepository()


def get_capability_sync_log_repository() -> DjangoSyncLogRepository:
    """Return the capability sync-log repository."""

    return DjangoSyncLogRepository()
