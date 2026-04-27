"""Signal repository provider for application consumers."""

from __future__ import annotations


def get_signal_repository():
    """Return the default signal repository."""

    from apps.signal.infrastructure.repositories import DjangoSignalRepository

    return DjangoSignalRepository()


def get_user_repository():
    """Return the default signal user repository."""

    from apps.signal.infrastructure.repositories import DjangoUserRepository

    return DjangoUserRepository()


def get_unified_signal_repository():
    """Return the default unified signal repository."""

    from apps.signal.infrastructure.repositories import UnifiedSignalRepository

    return UnifiedSignalRepository()
