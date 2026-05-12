"""Repository provider re-exports for application composition roots."""

from .repositories import (
    DjangoSignalRepository as _DjangoSignalRepository,
)
from .repositories import (
    DjangoUserRepository as _DjangoUserRepository,
)
from .repositories import (
    UnifiedSignalRepository as _UnifiedSignalRepository,
)

DjangoSignalRepository = _DjangoSignalRepository
DjangoUserRepository = _DjangoUserRepository
UnifiedSignalRepository = _UnifiedSignalRepository


def build_signal_repository():
    """Build the default concrete signal repository."""

    from .repositories import DjangoSignalRepository

    return DjangoSignalRepository()


def build_user_repository():
    """Build the default concrete signal user repository."""

    from .repositories import DjangoUserRepository

    return DjangoUserRepository()


def build_unified_signal_repository():
    """Build the default unified signal repository."""

    from .repositories import UnifiedSignalRepository

    return UnifiedSignalRepository()
