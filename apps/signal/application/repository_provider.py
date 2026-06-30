"""Signal repository provider for application consumers."""

from __future__ import annotations

from apps.signal.infrastructure.providers import (
    DjangoSignalRepository,  # noqa: F401
    SignalDiagnosticRepository,  # noqa: F401
    UnifiedSignalRepository,  # noqa: F401
    build_signal_diagnostic_repository,
    build_signal_repository,
    build_unified_signal_repository,
    build_user_repository,
)


def get_signal_repository():
    """Return the default signal repository."""

    return build_signal_repository()


def get_signal_diagnostic_repository() -> SignalDiagnosticRepository:
    """Return the default signal diagnostic repository."""

    return build_signal_diagnostic_repository()


def get_user_repository():
    """Return the default signal user repository."""

    return build_user_repository()


def get_unified_signal_repository():
    """Return the default unified signal repository."""

    return build_unified_signal_repository()
