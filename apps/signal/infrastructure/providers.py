"""Repository provider re-exports for application composition roots."""

from .repositories import *  # noqa: F401,F403
from .repositories import (
    DjangoSignalRepository,
    DjangoUserRepository,
    UnifiedSignalRepository,
)


def build_signal_repository() -> DjangoSignalRepository:
    """Build the default concrete signal repository."""

    return DjangoSignalRepository()


def build_user_repository() -> DjangoUserRepository:
    """Build the default concrete signal user repository."""

    return DjangoUserRepository()


def build_unified_signal_repository() -> UnifiedSignalRepository:
    """Build the default unified signal repository."""

    return UnifiedSignalRepository()
