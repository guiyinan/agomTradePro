"""Signal repository provider for application consumers."""

from __future__ import annotations

from apps.signal.infrastructure.providers import DjangoSignalRepository


def get_signal_repository() -> DjangoSignalRepository:
    """Return the default signal repository."""

    return DjangoSignalRepository()
