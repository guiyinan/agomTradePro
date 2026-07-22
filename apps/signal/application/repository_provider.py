"""Signal repository provider for application consumers."""

from __future__ import annotations

from apps.signal.infrastructure.providers import (
    DjangoSignalRepository as DjangoSignalRepository,
)
from apps.signal.infrastructure.providers import (
    DjangoUserRepository as DjangoUserRepository,
)
from apps.signal.infrastructure.providers import (
    SignalDiagnosticRepository as SignalDiagnosticRepository,
)
from apps.signal.infrastructure.providers import (
    UnifiedSignalRepository as UnifiedSignalRepository,
)
from apps.signal.infrastructure.providers import (
    build_signal_diagnostic_repository,
    build_signal_repository,
    build_unified_signal_repository,
    build_user_repository,
)


def get_signal_repository() -> DjangoSignalRepository:
    """Return the default signal repository."""

    return build_signal_repository()


def get_signal_diagnostic_repository() -> SignalDiagnosticRepository:
    """Return the default signal diagnostic repository."""

    return build_signal_diagnostic_repository()


def get_user_repository() -> DjangoUserRepository:
    """Return the default signal user repository."""

    return build_user_repository()


def get_unified_signal_repository() -> UnifiedSignalRepository:
    """Return the default unified signal repository."""

    return build_unified_signal_repository()
