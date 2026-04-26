"""Signal repository provider for application consumers."""

from __future__ import annotations

from apps.signal.infrastructure.providers import (
    DjangoSignalRepository,
    DjangoUserRepository,
    UnifiedSignalRepository,
)


def get_signal_repository() -> DjangoSignalRepository:
    """Return the default signal repository."""

    return DjangoSignalRepository()


def get_user_repository() -> DjangoUserRepository:
    """Return the default signal user repository."""

    return DjangoUserRepository()


def get_unified_signal_repository() -> UnifiedSignalRepository:
    """Return the default unified signal repository."""

    return UnifiedSignalRepository()
